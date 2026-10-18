import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.agent.evidence import EvidenceStore
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import finalize
from app.modules.agent.tools import ToolContext
from app.modules.chat.sending import send_message
from app.shared.models import (User, Course, Lesson, TranscriptSegment, ReviewCard,
                               Quiz, QuizQuestion, QuizAttempt, QuizAnswer, ChatConversation, now_utc)


class CombinedAnswersTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id="u", username="owner", password_hash="x")); self.db.flush()
        self.db.add(Course(id="c", owner_id="u", name="数据结构")); self.db.flush()
        self.db.add(Lesson(id="l", course_id="c", title="第一讲")); self.db.flush()
        self.db.add(TranscriptSegment(id="s", lesson_id="l", speaker="老师", start_ms=0,
            end_ms=1000, text="栈采用后进先出。"))
        self.db.add(ReviewCard(id="k", course_id="c", lesson_id="l", title="栈", body="后进先出", status="review"))
        self.db.add(Quiz(id="q", course_id="c", title="第一讲小测", status="ready")); self.db.flush()
        self.db.add(QuizQuestion(id="qq", quiz_id="q", position=1, kind="true_false", stem="栈采用后进先出。",
            options_json='["正确","错误"]', correct_option=0, explanation="原文明确说明。",
            source_segment_id="s", source_lesson_id="l", source_start_ms=0, source_excerpt="栈采用后进先出。"))
        self.db.add(QuizAttempt(id="a", quiz_id="q", user_id="u", correct_count=1, total_count=1)); self.db.flush()
        self.db.add(QuizAnswer(attempt_id="a", question_id="qq", selected_option=0, is_correct=True))
        self.db.add(ChatConversation(id="chat", user_id="u", course_id="c")); self.db.commit()
        self.context = ToolContext("owner", "c")
        self.evidence = EvidenceStore()

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def read(self, name, args):
        result = execute_tool(self.db, self.context, name, args)
        self.assertTrue(result["ok"], result)
        self.evidence.collect(self.db, self.context, name, result)
        return result["data"]

    def answer(self, payload):
        return finalize(self.db, self.context, json.dumps(payload), self.evidence, [])

    def test_progress_scores_learning_catalog_and_claims_are_all_shown(self):
        self.read("list_courses", {})
        self.read("get_course_progress", {})
        self.read("list_quiz_attempts", {"limit": 1})
        self.read("list_knowledge_points", {"status": "review"})
        self.read("get_transcript", {"lesson_id": "l"})
        result = self.answer({"claims": [{"text": "栈采用后进先出。", "source_ids": ["E1"]}],
            "catalog": {"course_ids": ["c"]}, "progress": {"query_ids": ["P1"]},
            "quiz_results": {"query_ids": ["Q1"]}, "learning": {"query_ids": ["L1"]}})
        for text in ("课程：数据结构", "缺少可用纪要的课次：1 节", "答对 1/1 题", "正确率 100%", "需要复习", "栈采用后进先出。 [1]"):
            self.assertIn(text, result["answer"])
        self.assertEqual(result["outcome"], "answered")

    def test_quiz_detail_and_classroom_citations_have_distinct_ids(self):
        self.read("get_quiz_attempt", {"attempt_id": "a"})
        self.read("get_transcript", {"lesson_id": "l"})
        result = self.answer({"claims": [{"text": "栈采用后进先出。", "source_ids": ["E1"]}],
            "quiz_results": {"query_ids": ["Q1"]}})
        self.assertEqual([c["id"] for c in result["citations"]], [1, 2])
        self.assertIn("课堂来源：第一讲 [1]", result["answer"])
        self.assertIn("栈采用后进先出。 [2]", result["answer"])
        self.assertEqual([c["segment_ids"] for c in result["citations"]], [["s"], ["s"]])

    def test_one_unavailable_section_preserves_other_verified_results(self):
        self.read("get_course_progress", {})
        self.read("list_quiz_attempts", {})
        with patch.object(self.evidence.progress, "answer", side_effect=HTTPException(404, "内部不可访问信息")):
            result = self.answer({"claims": [], "progress": {"query_ids": ["P1"]},
                "quiz_results": {"query_ids": ["Q1"]}})
        self.assertIn("答对 1/1 题", result["answer"])
        self.assertIn("课程进度当前无法核对", result["answer"])
        self.assertNotIn("内部不可访问信息", result["answer"])

    def test_invented_query_is_rejected_even_with_valid_other_result(self):
        self.read("get_course_progress", {})
        with self.assertRaises(HTTPException):
            self.answer({"claims": [], "progress": {"query_ids": ["P1"]},
                "quiz_results": {"query_ids": ["Q99"]}})

    def test_combined_statistics_recheck_changes(self):
        self.read("get_course_progress", {})
        self.read("list_knowledge_points", {})
        self.db.get(ReviewCard, "k").status = "mastered"; self.db.commit()
        result = self.answer({"claims": [], "progress": {"query_ids": ["P1"]}, "learning": {"query_ids": ["L1"]}})
        self.assertIn("需要复习 0 个", result["answer"])
        self.assertIn("栈 · 已掌握", result["answer"])

    def test_deleted_course_does_not_leak_cached_statistics(self):
        self.read("get_course_progress", {})
        self.db.get(Course, "c").deleted_at = now_utc(); self.db.commit()
        result = self.answer({"claims": [], "progress": {"query_ids": ["P1"]}})
        self.assertEqual(result["outcome"], "operation_failed")
        self.assertNotIn("共 1 节课", result["answer"])

    @patch("app.modules.agent.loop.complete")
    def test_chat_saves_both_query_results(self, model):
        def call(name, args, identity):
            return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}
        model.side_effect = [call("get_course_progress", {}, "p"), call("list_quiz_attempts", {"limit": 1}, "q"),
            {"content": '{"claims":[],"progress":{"query_ids":["P1"]},"quiz_results":{"query_ids":["Q1"]}}'}]
        result = send_message(self.db, "chat", "owner", "查课程进度和最近一次小测成绩", "request")
        self.assertIn("缺少可用纪要", result["messages"][-1]["content"])
        self.assertIn("答对 1/1 题", result["messages"][-1]["content"])

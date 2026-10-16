import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from test_course_agent import call
from app.shared.models import Course, Lesson, Quiz, QuizAttempt, QuizQuestion, ReviewCard, TranscriptSegment, User, now_utc
from app.modules.agent.evidence import EvidenceStore
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import finalize, run_agent
from app.modules.agent.tools import ToolContext
from app.modules.chat.conversations import create_course_conversation, create_global_conversation
from app.modules.chat.messages import read_messages
from app.modules.chat.sending import send_message
from app.modules.quizzes.schemas import QuizSubmit
from app.modules.quizzes.service import submit_quiz


def result_answer(*keys, learning=None):
    payload = {"claims": [], "quiz_results": {"query_ids": list(keys)}}
    if learning:
        payload["learning"] = {"query_ids": learning}
    return {"role": "assistant", "content": json.dumps(payload)}


class AgentQuizResultsTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def attempt(self, db, selected=1):
        question = db.get(Quiz, "q").questions[0]
        question.source_lesson_id, question.source_segment_id = "l", "s"
        return submit_quiz(db, "q", QuizSubmit(answers={"question": selected}), "owner")

    def read(self, db, args=None, context=None):
        return execute_tool(db, context or ToolContext("owner"), "list_quiz_attempts", args or {})

    def detail(self, db, identity, context=None, **args):
        return execute_tool(db, context or ToolContext("owner"), "get_quiz_attempt", {"attempt_id": identity, **args})

    def test_unsubmitted_quiz_has_no_score_or_answers_and_parameters_are_strict(self):
        with Session(self.engine) as db:
            data = self.read(db, {"quiz_id": "q"})["data"]
            self.assertEqual((data["total"], data["items"]), (0, []))
            self.assertIsNone(data["page_summary"]["accuracy_percent"])
            self.assertNotIn("correct_option", json.dumps(data))
            self.assertNotIn("explanation", json.dumps(data))
            self.assertEqual(self.detail(db, "q")["error"]["code"], "not_found")
            for args in ({"limit": True}, {"limit": 51}, {"offset": -1}, {"username": "other"}):
                self.assertEqual(self.read(db, args)["error"]["code"], "invalid_arguments")
            self.assertEqual(self.detail(db, "q", limit=16)["error"]["code"], "invalid_arguments")

    def test_recent_history_counts_repeated_attempts_and_weights_only_displayed_page(self):
        with Session(self.engine) as db:
            first = self.attempt(db)
            second = self.attempt(db, 0)
            db.get(QuizAttempt, first["id"]).created_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
            db.get(QuizAttempt, second["id"]).created_at = datetime(2026, 10, 2, tzinfo=timezone.utc)
            quiz = Quiz(id="q2", course_id="c", title="课堂专项", status="ready")
            quiz.questions = [QuizQuestion(id=f"second-{i}", position=i, kind="true_false", stem="题目",
                options_json='["正确","错误"]', correct_option=0, explanation="解析", source_start_ms=0, source_excerpt="原文") for i in (1, 2)]
            db.add(quiz); db.commit()
            latest = submit_quiz(db, "q2", QuizSubmit(answers={"second-1": 0, "second-2": 1}), "owner")
            data = self.read(db, {"limit": 2})["data"]
            self.assertEqual([row["id"] for row in data["items"]], [latest["id"], second["id"]])
            self.assertEqual((data["total"], data["next_offset"]), (3, 2))
            self.assertEqual(data["page_summary"], {"attempt_count": 2, "correct_count": 2, "total_count": 3, "accuracy_percent": 66.7})
            self.assertEqual(self.read(db, {"quiz_id": "q"})["data"]["total"], 2)
            self.assertEqual(self.read(db, {"query": "专项"})["data"]["total"], 1)
            self.assertEqual(self.read(db, {"query": "%"})["data"]["total"], 0)
            self.assertEqual(self.read(db, {"offset": 2})["data"]["items"][0]["id"], first["id"])
            self.assertIsInstance(data["items"][0]["created_at"], str)
            self.assertNotIn("correct_option", json.dumps(data))

    def test_owner_course_and_lesson_scopes_cannot_leak_other_results(self):
        with Session(self.engine) as db:
            own = self.attempt(db)
            db.add(User(id="other", username="other", password_hash="x")); db.flush()
            db.add_all([Course(id="c2", owner_id="u", name="数学"), Course(id="foreign", owner_id="other", name="私有课程")]); db.flush()
            db.add(Lesson(id="l2", course_id="c2", title="另一节")); db.flush()
            db.add(Quiz(id="foreign-q", course_id="foreign", title="私有小测")); db.flush()
            db.add_all([QuizAttempt(id="foreign-a", quiz_id="foreign-q", user_id="other", correct_count=1, total_count=1),
                        QuizAttempt(id="shared-a", quiz_id="q", user_id="other", correct_count=1, total_count=1)]); db.commit()
            self.assertEqual(self.read(db)["data"]["total"], 1)
            self.assertEqual(self.read(db, context=ToolContext("other"))["data"]["total"], 1)
            for args in ({"course_id": "foreign"}, {"quiz_id": "foreign-q"}, {"course_id": "c2", "quiz_id": "q"}):
                self.assertEqual(self.read(db, args)["error"]["code"], "not_found")
            self.assertEqual(self.read(db, {"course_id": "c2"}, ToolContext("owner", "c"))["error"]["code"], "not_found")
            for identity, context in ((own["id"], ToolContext("other")), ("shared-a", ToolContext("owner")),
                                      ("foreign-a", ToolContext("owner")), (own["id"], ToolContext("owner", "c2"))):
                self.assertEqual(self.detail(db, identity, context)["error"]["code"], "not_found")
            self.assertEqual(self.read(db, context=ToolContext("owner", "c", "l"))["data"]["total"], 1)
            quiz = db.get(Quiz, "q")
            quiz.lesson_id = None; quiz.lesson_ids_json = '["l","l2"]'; db.commit()
            self.assertEqual(self.read(db, context=ToolContext("owner", "c", "l"))["data"]["total"], 0)
            self.assertEqual(self.detail(db, own["id"], ToolContext("owner", "c", "l"))["error"]["code"], "not_found")

    def test_detail_returns_real_choices_and_only_current_visible_classroom_sources(self):
        with Session(self.engine) as db:
            attempt = self.attempt(db)
            data = self.detail(db, attempt["id"])["data"]
            row = data["items"][0]
            self.assertEqual((row["selected_option"], row["correct_option"], row["is_correct"]), (1, 0, False))
            self.assertEqual((row["source_status"], row["source"]["excerpt"]), ("available", "原文"))
            self.assertEqual(self.detail(db, attempt["id"], offset=1)["data"]["items"], [])
            segment = db.get(TranscriptSegment, "s")
            segment.text = "已经改为新内容"; db.commit()
            row = self.detail(db, attempt["id"])["data"]["items"][0]
            self.assertEqual((row["source_status"], row["source"]), ("changed", None))
            db.add(Course(id="c2", owner_id="u", name="数学")); db.flush()
            db.get(Lesson, "l").course_id = "c2"; db.commit()
            row = self.detail(db, attempt["id"])["data"]["items"][0]
            self.assertEqual((row["source_status"], row["source"]), ("unavailable", None))
            self.assertNotIn("已经改为新内容", json.dumps(row))

    def test_recycled_course_or_lesson_hides_counts_and_details_even_after_read(self):
        for model in (Course, Lesson):
            with self.subTest(model=model.__name__), Session(self.engine) as db:
                attempt = self.attempt(db)
                identity = "c" if model is Course else "l"
                recycled = db.get(model, identity)
                recycled.deleted_at = now_utc(); db.commit()
                self.assertEqual(self.read(db)["data"]["total"], 0)
                self.assertEqual(self.detail(db, attempt["id"])["error"]["code"], "not_found")
                recycled.deleted_at = None; db.commit()

    def test_course_wide_quiz_can_keep_score_but_cannot_quote_recycled_lesson(self):
        with Session(self.engine) as db:
            attempt = self.attempt(db)
            db.get(Quiz, "q").lesson_id = None
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assertEqual(self.read(db)["data"]["total"], 1)
            row = self.detail(db, attempt["id"])["data"]["items"][0]
            self.assertEqual((row["source_status"], row["source"]), ("unavailable", None))

    def test_final_response_rereads_sources_and_rejects_invented_query_ids(self):
        with Session(self.engine) as db:
            attempt = self.attempt(db)
            evidence, context = EvidenceStore(), ToolContext("owner")
            result = self.detail(db, attempt["id"])
            evidence.collect(db, context, "get_quiz_attempt", result)
            db.get(TranscriptSegment, "s").text = "新文字"; db.commit()
            final = finalize(db, context, result_answer("Q1")["content"], evidence, [])
            self.assertEqual(final["citations"], [])
            self.assertIn("原课堂文字已变化", final["answer"])
            self.assertIn("你的选择：B. 错误", final["answer"])
            with self.assertRaises(HTTPException):
                finalize(db, context, result_answer("invented")["content"], evidence, [])
            db.get(Course, "c").deleted_at = now_utc(); db.commit()
            with self.assertRaises(HTTPException):
                finalize(db, context, result_answer("Q1")["content"], evidence, [])

    @patch("app.modules.agent.loop.complete")
    def test_global_and_course_chat_save_score_details_steps_and_classroom_citations(self, model):
        with Session(self.engine) as db:
            attempt = self.attempt(db)
            for creator in (lambda: create_global_conversation(db, "owner"), lambda: create_course_conversation(db, "c", "owner")):
                chat = creator()
                model.side_effect = [call("list_quiz_attempts", {"limit": 1}, "scores"),
                    call("get_quiz_attempt", {"attempt_id": attempt["id"]}, "detail"),
                    call("list_wrong_questions", {"status": "pending"}, "wrong"), result_answer("Q1", "Q2", learning=["L1"])]
                result = send_message(db, chat["id"], "owner", "看看最近一次小测成绩、选项和错题", "r")
                question, answer = result["messages"]
                self.assertEqual([step["label"] for step in question["steps"]], ["查询小测成绩", "读取答题记录", "查询错题本"])
                self.assertIn("正确率 0%", answer["content"])
                self.assertIn("正确答案：A. 正确", answer["content"])
                self.assertIn("错题（待巩固）：1 道", answer["content"])
                self.assertEqual(answer["citations"][0]["segment_ids"], ["s"])
                self.assertEqual(read_messages(db, chat["id"], "owner"), result)
                self.assertNotIn("generate_quiz", str(model.call_args.args[1]))
            self.assertEqual(db.get(ReviewCard, "r").status, "new")
            self.assertEqual(db.query(QuizAttempt).count(), 1)

    @patch("app.modules.agent.loop.complete")
    def test_empty_history_final_is_explicit_and_cannot_fabricate_a_score(self, model):
        with Session(self.engine) as db:
            model.side_effect = [call("list_quiz_attempts", {}, "scores"), result_answer("Q1")]
            result = run_agent(db, ToolContext("owner"), "我最近的小测表现怎么样")
            self.assertIn("没有符合条件的已提交答题记录", result["answer"])
            self.assertNotIn("正确率 0%", result["answer"])
            self.assertEqual(result["outcome"], "answered")

    @patch("app.modules.agent.loop.complete")
    def test_final_history_rechecks_count_and_score_instead_of_using_model_values(self, model):
        with Session(self.engine) as db:
            attempt = self.attempt(db)
            def complete(messages, tools, **kwargs):
                if len(model.mock_calls) == 1:
                    return call("list_quiz_attempts", {"limit": 1}, "scores")
                db.get(QuizAttempt, attempt["id"]).correct_count = 1; db.commit()
                return {"role": "assistant", "content": '{"claims":[],"quiz_results":{"query_ids":["Q1"],"score":999}}'}
            model.side_effect = complete
            result = run_agent(db, ToolContext("owner"), "最近一次成绩")
            self.assertIn("正确率 100%", result["answer"])
            self.assertNotIn("999", result["answer"])

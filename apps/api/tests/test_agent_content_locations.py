"""内容位置与学习状态的边界；模型边界模拟，业务与引用校验使用真实数据库。"""
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.agent.evidence import EvidenceStore
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import run_agent
from app.modules.agent.responses import parse_response
from app.modules.agent.tools import ToolContext
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.intent_schema import IntentPayload, TurnDecision
from app.modules.chat.messages import read_messages
from app.modules.chat.sending import send_message
from app.shared.models import Course, Lesson, ReviewCard, TranscriptSegment, User, now_utc


QUESTION = "我的二叉树的特点是在哪个课程的第几个课次"


def call(name, arguments, identity):
    return {"role": "assistant", "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def final(**payload):
    return {"role": "assistant", "content": json.dumps({"claims": [], **payload}, ensure_ascii=False)}


class ContentLocationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(id="u", username="owner", password_hash="x"),
                         User(id="other", username="other", password_hash="x")]); self.db.flush()
        self.db.add_all([Course(id="c", owner_id="u", name="数据结构"),
                         Course(id="c2", owner_id="u", name="算法"),
                         Course(id="foreign", owner_id="other", name="他人的课程")]); self.db.flush()
        self.db.add_all([Lesson(id="l", course_id="c", title="第二讲"),
                         Lesson(id="l2", course_id="c2", title="第二讲"),
                         Lesson(id="private", course_id="foreign", title="秘密课次")]); self.db.flush()
        self.db.add_all([TranscriptSegment(id="s", lesson_id="l", start_ms=12000, end_ms=20000,
                            text="二叉树每个节点最多有两个孩子。"),
                         TranscriptSegment(id="s2", lesson_id="l", start_ms=21000, end_ms=25000,
                            text="二叉树的左右子树不能互换。"),
                         TranscriptSegment(id="s3", lesson_id="l2", start_ms=30000, end_ms=40000,
                            text="二叉树可以递归遍历。"),
                         TranscriptSegment(id="secret", lesson_id="private", start_ms=0, end_ms=1000,
                            text="秘密原文。"),
                         ReviewCard(id="r", course_id="c", lesson_id="l", title="二叉树",
                                    body="二叉树每个节点最多有两个孩子。", status="review")]); self.db.commit()
        self.context = ToolContext("owner", action_hints={"answer_mode": "source_location", "semantic_queries": []})

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def evidence(self, context=None):
        store = EvidenceStore()
        context = context or self.context
        result = execute_tool(self.db, context, "get_transcript", {"lesson_id": "l"})
        store.collect(self.db, context, "get_transcript", result)
        return store

    def test_original_request_only_renders_verified_location_and_survives_reload(self):
        conversation = create_global_conversation(self.db, "owner")
        decision = TurnDecision(relation="new", intent=IntentPayload(answer_mode="source_location"))
        responses = [call("list_knowledge_points", {"query": "二叉树"}, "k"),
                     call("list_courses", {}, "c"), call("get_transcript", {"lesson_id": "l"}, "t"),
                     final(locations={"source_ids": ["E1", "E2"]}, learning={"query_ids": ["L1"]},
                           catalog={"course_ids": ["c"]},
                           claims=[{"text": "错误的课堂解释", "source_ids": ["E1"]}])]
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=decision), \
             patch("app.modules.agent.loop.complete", side_effect=responses):
            result = send_message(self.db, conversation["id"], "owner", QUESTION, "location-test")
        reply = result["messages"][-1]
        self.assertEqual(reply["content"], "找到相关内容：\n\n《数据结构》 · 第二讲 [1]")
        self.assertEqual(len(reply["citations"]), 1)
        self.assertEqual(reply["citations"][0]["start_ms"], 12000)
        self.assertEqual(read_messages(self.db, conversation["id"], "owner"), result)

    def test_legacy_wrong_final_is_repaired_to_location_instead_of_status_dump(self):
        with patch("app.modules.agent.loop.complete", side_effect=[
            call("list_knowledge_points", {"query": "二叉树"}, "k"),
            call("get_transcript", {"lesson_id": "l"}, "t"),
            final(learning={"query_ids": ["L1"]}), final(locations={"source_ids": ["E1"]})]) as model:
            result = run_agent(self.db, self.context, QUESTION)
        self.assertEqual(model.call_count, 4)
        self.assertIn("《数据结构》 · 第二讲", result["answer"])
        self.assertNotIn("状态", result["answer"])

    def test_multiple_course_matches_deduplicate_by_lesson_identity(self):
        store = self.evidence()
        result = execute_tool(self.db, self.context, "get_transcript", {"lesson_id": "l2"})
        store.collect(self.db, self.context, "get_transcript", result)
        answer = store.location_answer(self.db, self.context, {"source_ids": ["E1", "E2", "E3", "E1"]}, citation_offset=2)
        self.assertIn("《数据结构》 · 第二讲 [3]", answer["answer"])
        self.assertIn("《算法》 · 第二讲 [4]", answer["answer"])
        self.assertEqual(len(answer["citations"]), 2)

    def test_invented_previous_and_foreign_sources_cannot_be_used(self):
        store = self.evidence()
        for identity in ["E99", "secret"]:
            with self.assertRaises(ValueError):
                store.location_answer(self.db, self.context, {"source_ids": [identity]})
        result = execute_tool(self.db, self.context, "get_transcript", {"lesson_id": "private"})
        self.assertFalse(result["ok"])
        store.collect(self.db, self.context, "get_transcript", result)
        self.assertEqual(len(store.entries), 2)
        scoped = ToolContext("owner", "c2")
        self.assertEqual(store.location_answer(self.db, scoped, {"source_ids": ["E1"]})["citations"], [])

    def test_changed_removed_or_recycled_sources_do_not_produce_location(self):
        for action in ["changed", "deleted", "recycled"]:
            with self.subTest(action=action):
                store = self.evidence()
                segment, lesson = self.db.get(TranscriptSegment, "s"), self.db.get(Lesson, "l")
                if action == "changed": segment.text = "已修改"
                elif action == "deleted": self.db.delete(segment)
                else: lesson.deleted_at = now_utc()
                self.db.flush()
                answer = store.location_answer(self.db, self.context, {"source_ids": ["E1"]})
                self.assertEqual(answer["citations"], [])
                self.assertNotIn("《数据结构》", answer["answer"])
                self.db.rollback()

    def test_renamed_metadata_uses_current_records_without_guessing_ordinal(self):
        store = self.evidence()
        self.db.get(Course, "c").name = "结构课程"
        self.db.get(Lesson, "l").title = "树的性质专题"
        self.db.commit()
        answer = store.location_answer(self.db, self.context, {"source_ids": ["E1"]})
        self.assertIn("《结构课程》 · 树的性质专题", answer["answer"])
        self.assertNotIn("第二讲", answer["answer"])

    def test_mixed_question_keeps_explicit_learning_and_classroom_answer(self):
        with patch("app.modules.agent.loop.complete", side_effect=[
            call("list_knowledge_points", {"query": "二叉树"}, "k"),
            call("get_transcript", {"lesson_id": "l"}, "t"),
            final(locations={"source_ids": ["E1"]}, learning={"query_ids": ["L1"]},
                  claims=[{"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E1"]}])]):
            result = run_agent(self.db, ToolContext("owner", action_hints={"semantic_queries": ["learning"]}),
                               "二叉树在哪讲过？解释一下特点，并告诉我标记的学习状态")
        self.assertIn("需要复习", result["answer"])
        self.assertIn("《数据结构》 · 第二讲", result["answer"])
        self.assertIn("二叉树每个节点最多有两个孩子。", result["answer"])
        self.assertEqual([row["id"] for row in result["citations"]], [1, 2])

    def test_location_protocol_cannot_mix_clarification_or_claim_insufficient(self):
        for outcome in ["needs_input", "insufficient_evidence"]:
            with self.assertRaises(ValidationError):
                parse_response(json.dumps({"claims": [], "locations": {"source_ids": ["E1"]},
                                           "outcome": outcome, **({"question": "哪门课？"} if outcome == "needs_input" else {})}))
        self.assertNotIn("answer_mode", IntentPayload().legacy())
        with self.assertRaises(ValidationError):
            IntentPayload(answer_mode="source_location", queries=["learning"])

    def test_insufficient_and_necessary_clarification_remain_available(self):
        for payload in [final(outcome="insufficient_evidence"), final(outcome="needs_input", question="你指的是哪一种树？")]:
            with patch("app.modules.agent.loop.complete", return_value=payload):
                result = run_agent(self.db, self.context, QUESTION)
            self.assertEqual(result["citations"], [])
            self.assertNotIn("知识点", result["answer"])

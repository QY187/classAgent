import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import TranscriptSegment, Quiz, ChatMessage, now_utc
from app.modules.agent.executor import execute_tool
from app.modules.agent.schemas import QuizArguments
from app.modules.agent.tools import ToolContext
from app.modules.chat.quiz_actions import wants_quiz
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.chat.cancellation import stop_generation
from app.modules.quizzes.schemas import QuizGenerate
from app.modules.quizzes.service import generate_quiz


def call(name, args, identity):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class AgentQuizTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def seed(self, db):
        db.add_all([TranscriptSegment(id="s2", lesson_id="l", start_ms=2, end_ms=3, text="第二段原文依据"), TranscriptSegment(id="s3", lesson_id="l", start_ms=3, end_ms=4, text="第三段原文依据")]); db.commit()

    def generated(self, segments, count, question_type):
        return [{"kind": "single_choice", "stem": f"题目{i}", "options": ["A", "B", "C", "D"], "correct_option": 0, "explanation": "解析保密", "source": segment, "evidence": segment.text} for i, segment in enumerate(segments)]

    def responses(self):
        return [call("list_courses", {}, "a"), call("list_lessons", {"course_id": "c"}, "b"), call("generate_quiz", {"course_id": "c", "lesson_ids": ["l"], "count": 3, "question_type": "single_choice"}, "q")]

    def test_intent_parameters_and_no_write_capability_by_default(self):
        self.assertTrue(wants_quiz("请根据第二讲生成3道选择题"))
        clarification = [{"role": "user", "content": "生成3道小测题"}, {"role": "assistant", "content": "哪一节课？"}]
        self.assertTrue(wants_quiz("第二讲", clarification))
        self.assertFalse(wants_quiz("第二讲讲的是什么", clarification))
        for question in ("小测是什么", "不要生成小测", "能否生成小测", "怎么生成小测"):
            self.assertFalse(wants_quiz(question))
        with self.assertRaises(ValueError):
            QuizArguments(course_id="c", count=2)
        with Session(self.engine) as db:
            result = execute_tool(db, ToolContext("owner"), "generate_quiz", {"course_id": "c"})
            self.assertFalse(result["ok"])
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_real_service_result_history_and_retry_are_idempotent(self, complete, generator):
        with Session(self.engine) as db:
            self.seed(db); generator.side_effect = self.generated
            complete.side_effect = self.responses()
            chat = create_global_conversation(db, "owner")
            result = send_message(db, chat["id"], "owner", "请根据二叉树课次生成3道选择题", "r")
            artifact = result["messages"][0]["artifacts"][0]
            self.assertEqual(artifact["question_count"], 3)
            self.assertEqual(artifact["lesson_ids"], ["l"])
            self.assertNotIn("correct_option", str(result))
            self.assertNotIn("解析保密", str(result))
            self.assertEqual(result["messages"][0]["steps"][-1]["label"], "生成课堂小测")
            question = db.get(ChatMessage, result["messages"][0]["id"])
            original = generate_quiz(db, "c", QuizGenerate(count=3), "owner", agent_request_key=question.id)
            self.assertEqual(original["id"], artifact["id"])
            generator.assert_called_once()
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["artifacts"], [artifact])
            from app.shared.models import Lesson
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["artifacts"], [])
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(count=3), "owner", agent_request_key=question.id)

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_scope_must_be_discovered_and_foreign_access_is_denied(self, complete, generator):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            complete.side_effect = [self.responses()[-1]]
            result = send_message(db, chat["id"], "owner", "生成3道小测题", "r")
            self.assertIn("确认课程", result["messages"][-1]["content"])
            generator.assert_not_called()
            from app.shared.models import User
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(), "other", agent_request_key="foreign")

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_cancel_before_save_does_not_create_quiz(self, complete, generator):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_global_conversation(db, "owner")
            complete.side_effect = self.responses()
            def generate(*args):
                result = self.generated(*args)
                stop_generation(db, chat["id"], "owner", "r")
                return result
            generator.side_effect = generate
            result = send_message(db, chat["id"], "owner", "请生成3道小测题", "r")
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])

    @patch("app.modules.agent.loop.complete")
    def test_ambiguous_request_can_ask_for_scope_without_generation(self, complete):
        complete.return_value = {"role": "assistant", "content": '{"claims":[],"outcome":"needs_input","question":"你想根据哪门课程生成小测？"}'}
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            result = send_message(db, chat["id"], "owner", "给我生成5道小测题", "r")
            self.assertIn("哪门课程", result["messages"][-1]["content"])
            self.assertEqual(result["messages"][0]["artifacts"], [])

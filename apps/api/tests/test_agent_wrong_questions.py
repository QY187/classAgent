import json
import unittest
from unittest.mock import patch

from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from test_course_agent import call
from app.shared.models import Course, Lesson, Quiz, User, now_utc
from app.modules.agent.executor import execute_tool
from app.modules.agent.tools import ToolContext
from app.modules.agent.loop import run_agent
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.quizzes.schemas import QuizSubmit, WrongQuestionRetry
from app.modules.quizzes.service import submit_quiz, retry_wrong_question


class AgentWrongQuestionsTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def wrong(self, db):
        db.get(Quiz, "q").questions[0].source_lesson_id = "l"
        submit_quiz(db, "q", QuizSubmit(answers={"question": 1}), "owner")

    def read(self, db, args=None, context=None):
        return execute_tool(db, context or ToolContext("owner", "c"), "list_wrong_questions", args or {})

    def test_duplicate_wrong_attempts_counts_status_filters_and_no_answers(self):
        with Session(self.engine) as db:
            self.wrong(db); self.wrong(db)
            data = self.read(db, {"status": "pending", "query": "题目", "limit": 1})["data"]
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["items"][0]["wrong_count"], 2)
            self.assertEqual(data["items"][0]["retry_count"], 0)
            self.assertNotIn("correct_option", json.dumps(data))
            self.assertNotIn("explanation", json.dumps(data))
            self.assertIsInstance(data["items"][0]["last_wrong_at"], str)
            retry_wrong_question(db, "question", WrongQuestionRetry(selected_option=0), "owner")
            self.assertEqual(self.read(db, {"status": "pending"})["data"]["total"], 0)
            mastered = self.read(db, {"status": "mastered"})["data"]["items"][0]
            self.assertEqual((mastered["wrong_count"], mastered["retry_count"]), (2, 1))
            self.assertEqual(self.read(db, {"lesson_id": "l"})["data"]["total"], 1)
            self.assertEqual(self.read(db, {"offset": 1})["data"]["items"], [])

    def test_scope_and_user_isolation_and_deleted_quiz(self):
        with Session(self.engine) as db:
            self.wrong(db)
            db.add(User(id="other", username="other", password_hash="x")); db.flush()
            db.add_all([Course(id="c2", owner_id="u", name="数学"), Course(id="foreign", owner_id="other", name="私有课")]); db.flush()
            db.add(Lesson(id="l2", course_id="c2", title="数学课")); db.commit()
            self.assertEqual(self.read(db, context=ToolContext("other"))["data"]["total"], 0)
            for args in ({"course_id": "c2"}, {"course_id": "foreign"}, {"lesson_id": "l2"}):
                self.assertEqual(self.read(db, args)["error"]["code"], "not_found")
            self.assertEqual(self.read(db, {"status": "review"})["error"]["code"], "invalid_arguments")
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assertEqual(self.read(db)["data"]["total"], 0)

    @patch("app.modules.agent.loop.complete")
    def test_chat_shows_verified_wrong_questions_and_restores_steps(self, model):
        with Session(self.engine) as db:
            self.wrong(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("list_wrong_questions", {"status": "pending"}, "wrong"),
                {"role": "assistant", "content": '{"claims":[],"learning":{"query_ids":["L1"]}}'}]
            result = send_message(db, chat["id"], "owner", "我还有哪些错题没掌握", "r")
            self.assertIn("错题（待巩固）：1 道", result["messages"][-1]["content"])
            self.assertIn("小测答错 1 次、重练 0 次", result["messages"][-1]["content"])
            self.assertEqual(result["messages"][0]["steps"][0]["label"], "查询错题本")
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)

    @patch("app.modules.agent.loop.complete")
    def test_empty_wrongbook_is_explicit_and_does_not_generate(self, model):
        with Session(self.engine) as db:
            model.side_effect = [call("list_wrong_questions", {}, "wrong"),
                {"role": "assistant", "content": '{"claims":[],"learning":{"query_ids":["L1"]}}'}]
            result = run_agent(db, ToolContext("owner"), "哪些错题需要练习")
            self.assertIn("没有符合条件的错题", result["answer"])
            self.assertEqual(result["outcome"], "answered")
            self.assertNotIn("generate_quiz", str(model.call_args.args[1]))

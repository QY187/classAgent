import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.modules.chat.conversations import create_conversation
from app.modules.chat.cancellation import stop_generation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.shared.models import User, ChatConversation


class ChatCancellationTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.chat.sending.ask_course")
    def test_stop_preserves_validated_preview_once_and_excludes_it_from_context(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            preview = {"answer": "已校验结论 [1]", "citations": [{"id": 1, "lesson_id": "l"}]}
            def generate(*args, **kwargs):
                kwargs["on_progress"](preview)
                stop_generation(db, chat["id"], "owner", "r")
                stop_generation(db, chat["id"], "owner", "r")
                kwargs["on_check"]()
            ask.side_effect = generate
            result = send_message(db, chat["id"], "owner", "课堂问题", "r", on_progress=lambda value: None)
            self.assertEqual(len(result["messages"]), 2)
            self.assertEqual(result["messages"][-1]["content"], preview["answer"])
            self.assertEqual(result["messages"][-1]["citations"], preview["citations"])
            self.assertTrue(all(item["status"] == "cancelled" for item in result["messages"]))
            self.assertIsNone(db.get(ChatConversation, chat["id"]).generation_preview_json)
            with patch("app.modules.chat.sending.ask_course", return_value={"answer": "新答案", "citations": []}) as next_ask:
                send_message(db, chat["id"], "owner", "后续问题", "next")
                self.assertNotIn("history", next_ask.call_args.kwargs)

    @patch("app.modules.chat.sending.ask_course")
    def test_stopped_request_is_not_saved_or_restarted(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            def generate(*args, **kwargs):
                stopped = stop_generation(db, chat["id"], "owner", "r")
                self.assertFalse(stopped["conversation"]["generating"])
                return {"answer": "停止后不可保存", "citations": []}
            ask.side_effect = generate
            result = send_message(db, chat["id"], "owner", "课堂问题", "r")
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            self.assertEqual(len(result["messages"]), 1)
            send_message(db, chat["id"], "owner", "课堂问题", "r")
            self.assertEqual(ask.call_count, 1)
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            with self.assertRaises(HTTPException) as error:
                stop_generation(db, chat["id"], "other", "r")
            self.assertEqual(error.exception.status_code, 404)

    @patch("app.modules.chat.sending.ask_course")
    def test_old_worker_and_repeated_stop_do_not_affect_new_question(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            def generate(*args, **kwargs):
                stop_generation(db, chat["id"], "owner", "r")
                with patch("app.modules.chat.sending.ask_course", return_value={"answer": "新答案", "citations": []}) as second:
                    send_message(db, chat["id"], "owner", "新问题", "next")
                    self.assertNotIn("history", second.call_args.kwargs)
                stop_generation(db, chat["id"], "owner", "r")
                kwargs["on_check"]()
            ask.side_effect = generate
            result = send_message(db, chat["id"], "owner", "课堂问题", "r", on_progress=lambda data: None)
            self.assertEqual(len(result["messages"]), 3)
            self.assertEqual(result["messages"][-1]["content"], "新答案")

    def test_stop_requires_matching_existing_question(self):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            with self.assertRaises(HTTPException) as error:
                stop_generation(db, chat["id"], "owner", "missing")
            self.assertEqual(error.exception.status_code, 409)

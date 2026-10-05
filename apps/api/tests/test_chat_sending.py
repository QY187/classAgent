import unittest
import test_recycle_visibility as fixtures
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.modules.chat.conversations import create_conversation
from app.modules.chat.messages import read_messages
from app.modules.chat.sending import send_message
from app.shared.models import ChatConversation, now_utc


class ChatSendingTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.chat.sending.ask_course", return_value={"answer":"原文依据", "citations":[]})
    def test_follow_up_uses_only_this_conversation_completed_history(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            other = create_conversation(db, "l", "owner")
            send_message(db, other["id"], "owner", "其他对话", "other")
            send_message(db, chat["id"], "owner", "二叉树定义", "first")
            send_message(db, chat["id"], "owner", "能举个例子吗", "follow")
            context = ask.call_args.kwargs["history"]
            self.assertEqual([item["content"] for item in context], ["二叉树定义", "原文依据"])
            self.assertEqual(ask.call_args.kwargs["lesson_id"], "l")

    @patch("app.modules.chat.sending.ask_course", return_value={"answer":"有依据的答案", "citations":[{"id":1}]})
    def test_saving_and_same_request_is_idempotent(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            first = send_message(db, chat["id"], "owner", "课堂问题", "request")
            second = send_message(db, chat["id"], "owner", "课堂问题", "request")
            self.assertEqual(len(second["messages"]), 2)
            self.assertEqual(first["messages"][1]["citations"], [{"id":1}])
            ask.assert_called_once_with(db, "c", "owner", "课堂问题", lesson_id="l")
            with self.assertRaises(HTTPException):
                send_message(db, chat["id"], "owner", "另一个问题", "request")

    @patch("app.modules.chat.sending.ask_course")
    def test_failed_question_can_retry_without_duplicate(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            ask.side_effect = HTTPException(502, "暂时失败")
            with self.assertRaises(HTTPException):
                send_message(db, chat["id"], "owner", "课堂问题", "request")
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["status"], "failed")
            ask.side_effect = None; ask.return_value = {"answer":"答案", "citations":[]}
            result = send_message(db, chat["id"], "owner", "课堂问题", "request")
            self.assertEqual([m["status"] for m in result["messages"]], ["completed", "completed"])

    @patch("app.modules.chat.sending.ask_course")
    def test_busy_conversation_rejects_duplicate_generation(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            item = db.get(ChatConversation, chat["id"])
            item.generation_token = "active"; item.generating_at = now_utc(); db.commit()
            with self.assertRaises(HTTPException) as err:
                send_message(db, chat["id"], "owner", "课堂问题", "request")
            self.assertEqual(err.exception.status_code, 409)
            ask.assert_not_called()

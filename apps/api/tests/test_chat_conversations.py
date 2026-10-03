import unittest
import test_recycle_visibility as fixtures
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.shared.models import ChatMessage, Lesson, User, now_utc
from app.modules.chat.messages import read_messages
from app.modules.chat.conversations import create_conversation, list_conversations


class ChatConversationTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def test_history_keeps_order_and_checks_owner(self):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            db.add_all([ChatMessage(conversation_id=chat["id"], request_id="r", position=2, role="assistant", content="答案", citations_json='[{"id":1}]'),
                        ChatMessage(conversation_id=chat["id"], request_id="r", position=1, role="user", content="问题")])
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            result = read_messages(db, chat["id"], "owner")
            self.assertEqual([item["role"] for item in result["messages"]], ["user", "assistant"])
            self.assertEqual(result["messages"][1]["citations"], [{"id":1}])
            with self.assertRaises(HTTPException):
                read_messages(db, chat["id"], "other")

    def test_list_only_requested_lesson(self):
        with Session(self.engine) as db:
            first = create_conversation(db, "l", "owner")
            db.add(Lesson(id="second", course_id="c", title="另一课")); db.commit()
            create_conversation(db, "second", "owner")
            self.assertEqual([item["id"] for item in list_conversations(db, "l", "owner")], [first["id"]])

    def test_create_multiple_and_deny_other_account_or_recycled_lesson(self):
        with Session(self.engine) as db:
            first = create_conversation(db, "l", "owner")
            second = create_conversation(db, "l", "owner")
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(first["title"], "新对话")
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            with self.assertRaises(HTTPException) as err:
                create_conversation(db, "l", "other")
            self.assertEqual(err.exception.status_code, 404)
            db.rollback()
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            with self.assertRaises(HTTPException):
                create_conversation(db, "l", "owner")

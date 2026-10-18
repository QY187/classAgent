import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import test_recycle_visibility as fixtures
from app.shared.models import ChatConversation, Course, User, now_utc
from app.modules.chat.conversations import (
    create_global_conversation, create_course_conversation, create_conversation,
    list_global_conversations, list_course_conversations, list_conversations,
    set_conversation_pin,
)
from app.modules.chat.migrations import prepare_chat_pinning
from app.modules.chat.search import search_conversations


class ChatPinningTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def test_pin_persists_and_unpin_restores_order_without_changing_message_time(self):
        with Session(self.engine) as db:
            older = create_global_conversation(db, "owner")
            newer = create_global_conversation(db, "owner")
            item = db.get(ChatConversation, older["id"])
            item.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.commit(); db.refresh(item)
            original_time = item.updated_at
            self.assertFalse(older["is_pinned"])
            self.assertTrue(set_conversation_pin(db, older["id"], "owner", True)["is_pinned"])
            set_conversation_pin(db, older["id"], "owner", True)
            self.assertEqual(item.updated_at, original_time)
        with Session(self.engine) as db:
            self.assertEqual([row["id"] for row in list_global_conversations(db, "owner")], [older["id"], newer["id"]])
            set_conversation_pin(db, older["id"], "owner", False)
            self.assertEqual([row["id"] for row in list_global_conversations(db, "owner")], [newer["id"], older["id"]])

    def test_course_lesson_and_search_lists_prioritize_pins(self):
        with Session(self.engine) as db:
            older = create_conversation(db, "l", "owner")
            newer = create_course_conversation(db, "c", "owner")
            another = create_conversation(db, "l", "owner")
            db.get(ChatConversation, older["id"]).updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.commit()
            set_conversation_pin(db, older["id"], "owner", True)
            self.assertEqual(list_course_conversations(db, "c", "owner", include_lessons=True)[0]["id"], older["id"])
            self.assertEqual(list_conversations(db, "l", "owner")[0]["id"], older["id"])
            self.assertEqual(search_conversations(db, "owner", "新对话")[0]["id"], older["id"])
            self.assertEqual([row["id"] for row in list_course_conversations(db, "c", "owner")], [newer["id"]])
            self.assertFalse(db.get(ChatConversation, another["id"]).is_pinned)

    def test_other_account_and_recycled_course_cannot_be_pinned(self):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            with self.assertRaises(HTTPException) as denied:
                set_conversation_pin(db, chat["id"], "other", True)
            self.assertEqual(denied.exception.status_code, 404)
            db.rollback()
            self.assertFalse(db.get(ChatConversation, chat["id"]).is_pinned)
            db.get(Course, "c").deleted_at = now_utc(); db.commit()
            with self.assertRaises(HTTPException):
                set_conversation_pin(db, chat["id"], "owner", True)

    def test_migration_preserves_old_rows_defaults_and_is_repeatable(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            prepare_chat_pinning(engine)
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE chat_conversations (id VARCHAR(36) PRIMARY KEY)"))
                connection.execute(text("INSERT INTO chat_conversations (id) VALUES ('old')"))
            prepare_chat_pinning(engine)
            prepare_chat_pinning(engine)
            self.assertIn("is_pinned", {column["name"] for column in inspect(engine).get_columns("chat_conversations")})
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT id, is_pinned FROM chat_conversations")).one(), ("old", 0))
        finally:
            engine.dispose()

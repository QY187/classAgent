import unittest
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import ChatConversation, ChatMessage, Course, User, now_utc
from app.modules.chat.archive import set_archived, list_archived
from app.modules.chat.conversations import create_global_conversation, create_course_conversation, create_conversation, list_global_conversations, list_course_conversations, list_conversations, set_conversation_pin
from app.modules.chat.messages import read_messages
from app.modules.chat.search import search_conversations
from app.modules.chat.sending import send_message
from app.modules.chat.migrations import prepare_chat_archive


class ChatArchiveTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def test_archive_preserves_messages_pin_and_time_and_restore(self):
        with Session(self.engine) as db:
            item = create_global_conversation(db, "owner")
            set_conversation_pin(db, item["id"], "owner", True)
            db.add(ChatMessage(conversation_id=item["id"], request_id=str(uuid4()), position=1, role="assistant", content="保留原文", status="completed"))
            db.commit()
            original = db.get(ChatConversation, item["id"]).updated_at
            set_archived(db, item["id"], "owner", True)
            set_archived(db, item["id"], "owner", True)
            self.assertEqual(list_global_conversations(db, "owner"), [])
            self.assertEqual(search_conversations(db, "owner", "新对话"), [])
            self.assertEqual(list_archived(db, "owner")[0]["id"], item["id"])
            self.assertEqual(read_messages(db, item["id"], "owner")["messages"][0]["content"], "保留原文")
            with self.assertRaises(HTTPException) as denied:
                send_message(db, item["id"], "owner", "继续提问", str(uuid4()))
            self.assertEqual(denied.exception.status_code, 409)
            db.rollback()
            restored = set_archived(db, item["id"], "owner", False)
            self.assertTrue(restored["is_pinned"])
            self.assertEqual(restored["updated_at"], original)
        with Session(self.engine) as db:
            self.assertEqual(list_archived(db, "owner"), [])
            self.assertEqual(list_global_conversations(db, "owner")[0]["id"], item["id"])

    def test_course_and_lesson_lists_hide_archived_and_ownership_is_enforced(self):
        with Session(self.engine) as db:
            course = create_course_conversation(db, "c", "owner")
            lesson = create_conversation(db, "l", "owner")
            for item in (course, lesson):
                set_archived(db, item["id"], "owner", True)
            self.assertEqual(list_course_conversations(db, "c", "owner", True), [])
            self.assertEqual(list_conversations(db, "l", "owner"), [])
            self.assertEqual(len(list_archived(db, "owner")), 2)
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            self.assertEqual(list_archived(db, "other"), [])
            with self.assertRaises(HTTPException) as denied:
                set_archived(db, course["id"], "other", False)
            self.assertEqual(denied.exception.status_code, 404)
            db.rollback()
            db.get(Course, "c").deleted_at = now_utc(); db.commit()
            self.assertEqual(list_archived(db, "owner"), [])

    def test_generating_conversation_cannot_be_archived(self):
        with Session(self.engine) as db:
            item = create_global_conversation(db, "owner")
            conversation = db.get(ChatConversation, item["id"])
            conversation.generation_token = "running"
            conversation.generating_at = now_utc(); db.commit()
            with self.assertRaises(HTTPException) as denied:
                set_archived(db, item["id"], "owner", True)
            self.assertEqual(denied.exception.status_code, 409)
            db.rollback()
            self.assertFalse(db.get(ChatConversation, item["id"]).is_archived)

    def test_old_table_migration_is_repeatable(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            prepare_chat_archive(engine)
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE chat_conversations (id TEXT PRIMARY KEY)"))
                connection.execute(text("INSERT INTO chat_conversations VALUES ('old')"))
            prepare_chat_archive(engine); prepare_chat_archive(engine)
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT is_archived FROM chat_conversations WHERE id='old'")).scalar(), 0)
        finally:
            engine.dispose()

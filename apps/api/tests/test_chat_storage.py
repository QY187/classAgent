import unittest
import test_recycle_visibility as fixtures
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.shared.models import ChatConversation, ChatMessage, Lesson, now_utc


class ChatStorageTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def test_message_citation_snapshot_and_cascade(self):
        with Session(self.engine) as db:
            db.add(ChatConversation(id="chat", lesson_id="l", user_id="u")); db.flush()
            db.add(ChatMessage(id="msg", conversation_id="chat", request_id="r", position=1,
                               role="assistant", content="回答", citations_json='[{"snippet":"课堂原文"}]'))
            db.commit()
            self.assertIn("课堂原文", db.get(ChatMessage, "msg").citations_json)
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assertEqual(list(db.scalars(select(ChatMessage))), [])
            db.execute(delete(ChatConversation.__table__).where(ChatConversation.__table__.c.id == "chat")); db.commit()
            self.assertEqual(list(db.scalars(select(ChatMessage).execution_options(include_deleted=True))), [])

    def test_conversation_follows_lesson_recycle_and_purge(self):
        with Session(self.engine) as db:
            db.add(ChatConversation(id="chat", lesson_id="l", user_id="u")); db.commit()
            lesson = db.get(Lesson, "l")
            lesson.deleted_at = now_utc(); db.commit()
            self.assertEqual(list(db.scalars(select(ChatConversation))), [])
            lesson.deleted_at = None; db.commit()
            self.assertEqual(db.scalar(select(ChatConversation)).title, "新对话")
            db.execute(delete(Lesson.__table__).where(Lesson.__table__.c.id == "l")); db.commit()
            self.assertEqual(list(db.scalars(select(ChatConversation).execution_options(include_deleted=True))), [])

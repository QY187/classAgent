import unittest
from unittest.mock import patch
import test_recycle_visibility as fixtures
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.shared.models import ChatConversation, ChatMessage, Course, Lesson, User, now_utc
from app.modules.chat.conversations import create_conversation, create_course_conversation, list_course_conversations
from app.modules.chat.messages import read_messages
from app.modules.chat.search import search_conversations
from app.modules.chat.sending import send_message


class CourseChatTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.chat.sending.ask_course", return_value={"answer":"课程答案", "citations":[]})
    def test_course_send_has_no_lesson_restriction(self, ask):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            result = send_message(db, chat["id"], "owner", "整门课程讲了什么", "r")
            ask.assert_called_once_with(db, "c", "owner", "整门课程讲了什么", lesson_id=None)
            self.assertEqual(result["messages"][1]["content"], "课程答案")

    def test_course_and_lesson_lists_are_independent(self):
        with Session(self.engine) as db:
            course_chat = create_course_conversation(db, "c", "owner")
            create_conversation(db, "l", "owner")
            self.assertEqual([item["id"] for item in list_course_conversations(db, "c", "owner")], [course_chat["id"]])
            self.assertEqual(course_chat["scope"], "course")
            self.assertEqual(len(search_conversations(db, "owner", "数据结构")), 2)
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            with self.assertRaises(HTTPException):
                create_course_conversation(db, "c", "other")

    def test_course_chat_survives_lesson_purge_and_follows_course_recycle(self):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            db.add(ChatMessage(conversation_id=chat["id"], request_id="r", position=1, role="user", content="问题")); db.commit()
            db.execute(delete(Lesson.__table__).where(Lesson.__table__.c.id == "l")); db.commit()
            self.assertEqual(len(read_messages(db, chat["id"], "owner")["messages"]), 1)
            course = db.get(Course, "c"); course.deleted_at = now_utc(); db.commit()
            self.assertEqual(list(db.scalars(select(ChatConversation))), [])
            self.assertEqual(list(db.scalars(select(ChatMessage))), [])
            course.deleted_at = None; db.commit()
            self.assertEqual(len(list_course_conversations(db, "c", "owner")), 1)
            db.execute(delete(Course.__table__).where(Course.__table__.c.id == "c")); db.commit()
            self.assertEqual(list(db.scalars(select(ChatMessage).execution_options(include_deleted=True))), [])

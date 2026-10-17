import unittest
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.shared.models import Course, AgentAction, ChatMessage
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.action_records import perform_for_message
from app.modules.chat.generation import GenerationStopped
from test_recycle_visibility import RecycleVisibilityTest


class ActionRecordsTest(unittest.TestCase):
    setUp = RecycleVisibilityTest.setUp
    tearDown = RecycleVisibilityTest.tearDown

    def prepare(self, db):
        data = create_course_conversation(db, "c", "owner")
        from app.shared.models import ChatConversation
        chat = db.get(ChatConversation, data["id"])
        chat.generation_token = "token"
        message = ChatMessage(conversation_id=chat.id, request_id="r", position=1, role="user", status="pending", content="明确操作")
        db.add(message); db.commit()
        return chat.id, message.id

    def test_write_and_receipt_are_atomic_and_retry_returns_same_result(self):
        with Session(self.engine) as db:
            chat, message = self.prepare(db)
            calls = []
            def handler(db):
                calls.append(True)
                course = Course(id="created", owner_id="u", name="测试")
                db.add(course); db.flush()
                return {"id": course.id, "message": "已创建测试"}
            def run(args):
                return perform_for_message(db, chat, "owner", message, "token", "test", args, handler, lambda *args: None)
            self.assertEqual(run({"name": "测试"}), run({"name": "测试"}))
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(list(db.scalars(select(AgentAction)))), 1)
            with self.assertRaises(HTTPException): run({"name": "另一个"})
            self.assertEqual(len(calls), 1)

    def test_failure_rolls_back_entity_and_stop_prevents_handler(self):
        with Session(self.engine) as db:
            chat, message = self.prepare(db)
            def fail(db):
                db.add(Course(id="temporary", owner_id="u", name="临时")); db.flush()
                raise RuntimeError("failed")
            with self.assertRaises(RuntimeError):
                perform_for_message(db, chat, "owner", message, "token", "test", {}, fail, lambda *a: None)
            self.assertIsNone(db.get(Course, "temporary"))
            self.assertEqual(list(db.scalars(select(AgentAction))), [])
            with self.assertRaises(GenerationStopped):
                perform_for_message(db, chat, "owner", message, "old-token", "test", {}, fail, lambda *a: None)
            self.assertIsNone(db.get(Course, "temporary"))

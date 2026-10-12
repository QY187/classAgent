import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.core.db import Base
from app.shared.models import User, Course, Lesson, ChatConversation, ChatMessage, now_utc
from app.modules.chat.conversations import create_global_conversation, create_course_conversation, create_conversation, list_global_conversations, rename_conversation
from app.modules.chat.messages import read_messages
from app.modules.chat.search import search_conversations
from app.modules.chat.sending import send_message
from app.modules.chat.deletion import delete_conversation
from app.modules.chat.cancellation import stop_generation
from app.modules.agent.tools import ToolContext
from app.modules.agent.loop import run_agent


class GlobalChatTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(id="u", username="owner", password_hash="x"), User(id="other", username="other", password_hash="x")]); self.db.flush()
        self.db.add(Course(id="c", owner_id="u", name="数据结构")); self.db.flush()
        self.db.add(Lesson(id="l", course_id="c", title="第二讲")); self.db.commit()

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_scopes_are_independent_and_main_chat_needs_no_course(self):
        global_chat = create_global_conversation(self.db, "owner")
        create_course_conversation(self.db, "c", "owner")
        create_conversation(self.db, "l", "owner")
        create_global_conversation(self.db, "other")
        self.assertEqual(global_chat["scope"], "global")
        self.assertEqual([item["id"] for item in list_global_conversations(self.db, "owner")], [global_chat["id"]])
        with self.assertRaises(HTTPException):
            read_messages(self.db, global_chat["id"], "other")
        self.db.add(ChatConversation(user_id="u", course_id="c", lesson_id="l"))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    @patch("app.modules.chat.sending.run_agent", return_value={"answer": "主对话回答", "citations": [], "steps": []})
    def test_main_send_saves_history_and_request_is_idempotent(self, agent):
        chat = create_global_conversation(self.db, "owner")
        result = send_message(self.db, chat["id"], "owner", "我有哪些课程", "r")
        self.assertEqual(agent.call_args.args[1], ToolContext("owner"))
        self.assertEqual(result["messages"][1]["content"], "主对话回答")
        self.assertEqual(send_message(self.db, chat["id"], "owner", "我有哪些课程", "r"), result)
        agent.assert_called_once()

    def test_catalog_answer_only_renders_actual_tool_results(self):
        responses = [{"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function", "function": {"name": "list_courses", "arguments": "{}"}}]},
            {"role": "assistant", "content": '{"claims":[],"catalog":{"course_ids":["c","invented"],"lesson_ids":[]}}'}]
        with patch("app.modules.agent.loop.complete", side_effect=responses):
            result = run_agent(self.db, ToolContext("owner"), "我有哪些课程")
        self.assertEqual(result["answer"], "课程：数据结构")
        self.assertEqual(result["outcome"], "answered")
        self.assertEqual(result["citations"], [])

    def test_global_search_rename_delete_and_course_purge(self):
        chat = create_global_conversation(self.db, "owner")
        rename_conversation(self.db, chat["id"], "owner", "跨课程整理")
        self.assertEqual(search_conversations(self.db, "owner", "跨课程")[0]["scope"], "global")
        self.assertEqual(search_conversations(self.db, "other", "跨课程"), [])
        self.db.add(ChatMessage(conversation_id=chat["id"], position=1, request_id="r", role="user", content="问题")); self.db.commit()
        self.db.get(Course, "c").deleted_at = now_utc(); self.db.commit()
        self.assertEqual(len(read_messages(self.db, chat["id"], "owner")["messages"]), 1)
        self.db.execute(delete(Course.__table__).where(Course.id == "c")); self.db.commit()
        self.assertEqual(len(list_global_conversations(self.db, "owner")), 1)
        delete_conversation(self.db, chat["id"], "owner")
        self.assertEqual(list(self.db.scalars(select(ChatMessage))), [])

    def test_cancel_global_generation_and_reject_other_users(self):
        chat = create_global_conversation(self.db, "owner")
        stored = self.db.get(ChatConversation, chat["id"])
        stored.generation_token = "token"; stored.generating_at = now_utc()
        self.db.add(ChatMessage(conversation_id=chat["id"], position=1, request_id="r", role="user", content="问题", status="pending")); self.db.commit()
        with self.assertRaises(HTTPException):
            stop_generation(self.db, chat["id"], "other", "r")
        result = stop_generation(self.db, chat["id"], "owner", "r")
        self.assertFalse(result["conversation"]["generating"])
        self.assertEqual(result["messages"][0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()

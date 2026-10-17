import json
import unittest
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.shared.models import Course, AgentAction, ChatConversation, now_utc
from app.modules.chat.conversations import create_global_conversation, create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.chat.cancellation import stop_generation
from app.modules.chat.course_actions import requested_course, course_name
from app.modules.agent.executor import execute_tool
from app.modules.agent.tools import ToolContext
from test_recycle_visibility import RecycleVisibilityTest


def call(name, args, identity="create"):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}


class CreateCourseTest(unittest.TestCase):
    setUp = RecycleVisibilityTest.setUp
    tearDown = RecycleVisibilityTest.tearDown

    def test_only_explicit_instruction_and_exact_name(self):
        for text in ("不要创建数据结构课程", "创建课程怎么做", "是否可以创建数据结构课程", "老师说创建数据结构课程", "原文中创建数据结构课程", "资料内容是创建网络课程", "阅读这段文字：创建网络课程"):
            self.assertFalse(requested_course(text), text)
        self.assertEqual(course_name("帮我创建数据结构课程，再添加第三讲。"), "数据结构")
        self.assertEqual(course_name("新建一个叫计算机网络的课程"), "计算机网络")
        self.assertIsNone(course_name("创建课程"))
        with Session(self.engine) as db:
            self.assertFalse(execute_tool(db, ToolContext("owner"), "create_course", {"name": "误创建"})["ok"])

    @patch("app.modules.agent.loop.complete")
    def test_missing_name_can_be_clarified(self, model):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            model.return_value = {"content": '{"claims":[],"outcome":"needs_input","question":"课程名称是什么？"}'}
            send_message(db, chat["id"], "owner", "创建课程", "ask")
            model.side_effect = [call("create_course", {"name": "网络"}), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "网络", "name")
            self.assertEqual(result["messages"][-1]["content"], "已创建课程：网络。")

    @patch("app.modules.agent.loop.complete")
    def test_create_artifact_persistence_repeat_and_no_model_fake_success(self, model):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            model.side_effect = [call("create_course", {"name": "网络课程"}), call("create_course", {"name": "网络"}, "repeat"), {"content": "随意编造的完成结果"}]
            result = send_message(db, chat["id"], "owner", "帮我创建网络课程", "r")
            self.assertEqual(result["messages"][-1]["content"], "已创建课程：网络。")
            artifact = result["messages"][0]["artifacts"][0]
            self.assertEqual(db.get(Course, artifact["id"]).owner_id, "u")
            self.assertEqual(len(list(db.scalars(select(AgentAction)))), 1)
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)
            send_message(db, chat["id"], "owner", "帮我创建网络课程", "r")
            self.assertEqual(model.call_count, 3)
            db.get(Course, artifact["id"]).deleted_at = now_utc(); db.commit()
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["artifacts"], [])

    @patch("app.modules.agent.loop.complete")
    def test_failed_answer_retry_does_not_duplicate_saved_course(self, model):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            model.side_effect = [call("create_course", {"name": "网络"}), HTTPException(502, "模型失败")]
            with self.assertRaises(HTTPException): send_message(db, chat["id"], "owner", "创建网络课程", "r")
            self.assertEqual(len(read_messages(db, chat["id"], "owner")["messages"][0]["artifacts"]), 1)
            model.side_effect = [call("create_course", {"name": "网络"}), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "创建网络课程", "r")
            self.assertIn("已创建", result["messages"][-1]["content"])
            self.assertEqual(len([c for c in db.scalars(select(Course)) if c.name == "网络"]), 1)

    @patch("app.modules.agent.loop.complete")
    def test_wrong_name_duplicate_course_scope_and_cancel_do_not_write(self, model):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            for i, (text, args) in enumerate((("创建网络课程", {"name": "猜测"}), ("创建数据结构课程", {"name": "数据结构"}))):
                model.side_effect = [call("create_course", args), {"content": '{"claims":[],"outcome":"needs_input","question":"请明确课程名称？"}'}]
                result = send_message(db, chat["id"], "owner", text, f"r{i}")
                self.assertEqual(result["messages"][-2]["steps"][0]["status"], "failed")
                self.assertEqual(result["messages"][-2]["artifacts"], [])
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("create_course", {"name": "网络"}), {"content": '{"claims":[],"outcome":"needs_input","question":"请进入主对话？"}'}]
            self.assertEqual(send_message(db, chat["id"], "owner", "创建网络课程", "scope")["messages"][0]["artifacts"], [])
            chat = create_global_conversation(db, "owner")
            model.side_effect = None; model.return_value = call("create_course", {"name": "网络"})
            result = send_message(db, chat["id"], "owner", "创建网络课程", "stop", on_step=lambda event: stop_generation(db, chat["id"], "owner", "stop"))
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            self.assertEqual(len(list(db.scalars(select(AgentAction)))), 0)

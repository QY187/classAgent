import json
import unittest
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.shared.models import Course, Lesson, AgentAction, now_utc
from app.modules.chat.conversations import create_global_conversation, create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.lesson_actions import lesson_request
from app.modules.agent.schemas import CreateLessonArguments
from test_recycle_visibility import RecycleVisibilityTest


def call(name, args, identity):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}


class CreateLessonTest(unittest.TestCase):
    setUp = RecycleVisibilityTest.setUp
    tearDown = RecycleVisibilityTest.tearDown

    def test_explicit_titles_and_date_validation(self):
        self.assertEqual(lesson_request("帮我创建数据结构课程，再添加第三讲。"), (True, "第三讲"))
        self.assertEqual(lesson_request("在数据结构课程下添加第三讲，日期为2026-10-03"), (True, "第三讲"))
        self.assertEqual(lesson_request("添加课次标题为树与遍历"), (True, "树与遍历"))
        for text in ("不要添加第三讲", "怎么添加第三讲", "老师说添加第三讲", "添加课程", "文本里添加第三讲"):
            self.assertFalse(lesson_request(text)[0])
        with self.assertRaises(ValueError): CreateLessonArguments(course_id="c", title="第三讲", lesson_date="2026-02-30")

    @patch("app.modules.agent.loop.complete")
    def test_stop_after_write_retains_receipt_and_recycled_lesson_hides_link(self, model):
        from app.modules.chat.cancellation import stop_generation
        from app.modules.chat.messages import read_messages
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            model.return_value = call("create_lesson", {"course_id": "c", "title": "第三讲"}, "add")
            def stop(event):
                if event["steps"][-1]["status"] == "completed":
                    stop_generation(db, chat["id"], "owner", "r")
            result = send_message(db, chat["id"], "owner", "添加第三讲", "r", on_step=stop)
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            artifact = result["messages"][0]["artifacts"][0]
            db.get(Lesson, artifact["id"]).deleted_at = now_utc(); db.commit()
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["artifacts"], [])

    @patch("app.modules.agent.loop.complete")
    def test_ambiguous_global_course_is_not_guessed(self, model):
        with Session(self.engine) as db:
            db.add(Course(id="duplicate", owner_id="u", name="数据结构")); db.commit()
            chat = create_global_conversation(db, "owner")
            model.side_effect = [call("list_courses", {}, "read"), call("create_lesson", {"course_id": "c", "title": "第三讲"}, "add"), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "在数据结构课程下添加第三讲", "r")
            self.assertEqual(result["messages"][0]["artifacts"], [])
            self.assertIn("唯一的目标课程", result["messages"][-1]["content"])

    @patch("app.modules.agent.loop.complete")
    def test_bound_course_add_and_preserve_page_order_rule(self, model):
        with Session(self.engine) as db:
            db.get(Lesson, "l").sort_order = 10; db.commit()
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("create_lesson", {"course_id": "c", "title": "第三讲"}, "add"), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "添加第三讲", "r")
            artifact = result["messages"][0]["artifacts"][0]
            lesson = db.get(Lesson, artifact["id"])
            self.assertEqual((lesson.course_id, lesson.lesson_date, lesson.sort_order), ("c", None, 9))
            self.assertIn("已在课程", result["messages"][-1]["content"])
            self.assertIn("第三讲", result["messages"][-1]["content"])

    @patch("app.modules.agent.loop.complete")
    def test_create_course_then_lesson_in_one_instruction(self, model):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            calls = 0
            def complete(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1: return call("create_course", {"name": "网络课程"}, "course")
                if calls == 2:
                    course = db.scalar(select(Course).where(Course.name == "网络"))
                    return call("create_lesson", {"course_id": course.id, "title": "第三讲"}, "lesson")
                return {"content": "任意成功描述被忽略"}
            model.side_effect = complete
            result = send_message(db, chat["id"], "owner", "帮我创建网络课程，再添加第三讲", "r")
            artifacts = result["messages"][0]["artifacts"]
            self.assertEqual({a["operation"] for a in artifacts}, {"create_course", "create_lesson"})
            self.assertEqual(len({a["course_id"] for a in artifacts}), 1)
            self.assertEqual(len(list(db.scalars(select(AgentAction)))), 2)
            self.assertIn("已创建课程：网络", result["messages"][-1]["content"])

    @patch("app.modules.agent.loop.complete")
    def test_existing_global_course_must_be_read_and_match_named_target(self, model):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            model.side_effect = [call("create_lesson", {"course_id": "c", "title": "第三讲"}, "early"),
                call("list_courses", {"query": "数据结构"}, "read"), call("create_lesson", {"course_id": "c", "title": "第三讲", "lesson_date": "2026-10-03"}, "add"), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "在数据结构课程下添加第三讲，日期为2026-10-03", "r")
            self.assertEqual([s["status"] for s in result["messages"][0]["steps"]], ["failed", "completed", "completed"])
            self.assertEqual(db.get(Lesson, result["messages"][0]["artifacts"][0]["id"]).lesson_date, "2026-10-03")

    @patch("app.modules.agent.loop.complete")
    def test_duplicate_unrequested_date_and_title_and_dependency_failure(self, model):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            for i, (question, args) in enumerate((("添加第三讲", {"course_id": "c", "title": "第三讲", "lesson_date": "2026-10-03"}),
                    ("添加第三讲", {"course_id": "c", "title": "第四讲"}), ("添加课次标题为二叉树", {"course_id": "c", "title": "二叉树"}))):
                model.side_effect = [call("create_lesson", args, "add"), {"content": "{}"}]
                result = send_message(db, chat["id"], "owner", question, f"r{i}")
                self.assertEqual(result["messages"][-2]["artifacts"], [])
                self.assertNotIn("已在课程", result["messages"][-1]["content"])
            chat = create_global_conversation(db, "owner")
            model.side_effect = [call("list_courses", {}, "read"), call("create_lesson", {"course_id": "c", "title": "第三讲"}, "add"), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "创建数据结构课程，再添加第三讲", "r")
            self.assertIn("先成功创建", result["messages"][-1]["content"])
            self.assertEqual(list(db.scalars(select(AgentAction))), [])

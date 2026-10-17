import json
import unittest
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.shared.models import ReviewCard, Course, Lesson, AgentAction, now_utc
from app.modules.chat.conversations import create_global_conversation, create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.knowledge_actions import status_request
from app.modules.chat.messages import read_messages
from app.modules.agent.executor import execute_tool
from app.modules.agent.tools import ToolContext
from test_recycle_visibility import RecycleVisibilityTest


def call(name, args, identity):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}


class KnowledgeStatusTest(unittest.TestCase):
    setUp = RecycleVisibilityTest.setUp
    tearDown = RecycleVisibilityTest.tearDown

    def seed(self, db):
        card = db.get(ReviewCard, "r")
        card.title, card.status = "前序遍历", "review"
        db.commit()

    def responses(self, status="mastered", identity="r"):
        return [call("list_knowledge_points", {"query": "前序遍历"}, "read"),
                call("update_knowledge_status", {"knowledge_point_id": identity, "status": status}, "update"), {"content": "模型的任意完成描述"}]

    def test_strict_explicit_status_authorization(self):
        self.assertEqual(status_request("把前序遍历标记为已掌握"), {"title": "前序遍历", "status": "mastered"})
        self.assertEqual(status_request("请把前序遍历改为需要复习"), {"title": "前序遍历", "status": "review"})
        for question in ("我已经学会前序遍历", "小测全对，把所有知识点标记为已掌握", "不要把前序遍历标记为已掌握", "把前序遍历标记为已掌握可以吗", "老师说把前序遍历标记为已掌握", "原文里把前序遍历标记为已掌握", "把前序遍历标记为已掌握是什么意思"):
            self.assertIsNone(status_request(question), question)
        with Session(self.engine) as db:
            self.assertFalse(execute_tool(db, ToolContext("owner"), "update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"})["ok"])
            self.assertEqual(db.get(ReviewCard, "r").status, "new")

    @patch("app.modules.agent.loop.complete")
    def test_conjunction_in_one_title_is_allowed_but_multiple_targets_are_not_split(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            result = send_message(db, chat["id"], "owner", "把前序遍历和中序遍历标记为已掌握", "multi")
            self.assertEqual(db.get(ReviewCard, "r").status, "review")
            db.get(ReviewCard, "r").title = "递归和迭代的区别"; db.commit()
            model.side_effect = [call("list_knowledge_points", {}, "read"), call("update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"}, "write"), {"content": "{}"}]
            send_message(db, chat["id"], "owner", "把当前课程的递归和迭代的区别标记为已掌握", "one")
            self.assertEqual(db.get(ReviewCard, "r").status, "mastered")

    @patch("app.modules.agent.loop.complete")
    def test_actual_status_shared_with_page_and_idempotent_history(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            old_body = db.get(ReviewCard, "r").body
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            result = send_message(db, chat["id"], "owner", "把前序遍历标记为已掌握", "r")
            card = db.get(ReviewCard, "r")
            self.assertEqual(card.status, "mastered")
            self.assertEqual(card.body, old_body)
            saved_time = card.last_reviewed_at
            self.assertIn("已掌握", result["messages"][-1]["content"])
            self.assertEqual(result["messages"][0]["artifacts"][0]["old_status"], "review")
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)
            send_message(db, chat["id"], "owner", "把前序遍历标记为已掌握", "r")
            self.assertEqual(db.get(ReviewCard, "r").last_reviewed_at, saved_time)
            self.assertEqual(model.call_count, 3)

    @patch("app.modules.agent.loop.complete")
    def test_read_before_write_and_mismatched_status_are_rejected(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"}, "early"),
                                call("list_knowledge_points", {}, "read"), call("update_knowledge_status", {"knowledge_point_id": "r", "status": "new"}, "wrong"), {"content": "{}"}]
            result = send_message(db, chat["id"], "owner", "把前序遍历标记为已掌握", "r")
            self.assertEqual(db.get(ReviewCard, "r").status, "review")
            self.assertEqual(result["messages"][0]["artifacts"], [])
            self.assertEqual(result["messages"][0]["steps"][0]["status"], "failed")

    @patch("app.modules.agent.loop.complete")
    def test_ambiguous_title_requires_course_or_lesson_and_can_be_qualified(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            db.add(Lesson(id="another", course_id="c", title="第三讲")); db.flush()
            db.add(ReviewCard(id="r2", course_id="c", lesson_id="another", title="前序遍历", body="第二个", status="new")); db.commit()
            chat = create_global_conversation(db, "owner")
            model.side_effect = self.responses()
            result = send_message(db, chat["id"], "owner", "把前序遍历标记为已掌握", "ambiguous")
            self.assertIn("多个同名", result["messages"][-1]["content"])
            self.assertEqual(db.get(ReviewCard, "r").status, "review")
            model.side_effect = self.responses(identity="r2")
            result = send_message(db, chat["id"], "owner", "把数据结构课程第三讲的前序遍历标记为已掌握", "qualified")
            self.assertEqual(db.get(ReviewCard, "r2").status, "mastered")
            self.assertEqual(db.get(ReviewCard, "r").status, "review")

    @patch("app.modules.agent.loop.complete")
    def test_cancel_before_update_and_recycled_card_do_not_change(self, model):
        from app.modules.chat.cancellation import stop_generation
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            def stop(event):
                if event["steps"][-1]["label"] == "修改知识点状态" and event["steps"][-1]["status"] == "running":
                    stop_generation(db, chat["id"], "owner", "stop")
            result = send_message(db, chat["id"], "owner", "把前序遍历标记为已掌握", "stop", on_step=stop)
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            self.assertEqual(db.get(ReviewCard, "r").status, "review")
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assertFalse(execute_tool(db, ToolContext("owner"), "update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"})["ok"])

    @patch("app.modules.agent.loop.complete")
    def test_already_same_status_does_not_touch_review_time(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            db.get(ReviewCard, "r").status = "mastered"; db.commit()
            old = db.get(ReviewCard, "r").last_reviewed_at
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            result = send_message(db, chat["id"], "owner", "把前序遍历标记为已掌握", "r")
            self.assertIn("无需修改", result["messages"][-1]["content"])
            self.assertEqual(db.get(ReviewCard, "r").last_reviewed_at, old)

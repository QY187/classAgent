import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from test_course_agent import call
from app.shared.models import Course, Lesson, ReviewCard, User, now_utc
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages


class AgentKnowledgeTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def seed(self, db):
        db.add(User(id="other", username="other", password_hash="x")); db.flush()
        db.add_all([Course(id="c2", owner_id="u", name="数学"), Course(id="foreign", owner_id="other", name="其他人的课")]); db.flush()
        db.add_all([Lesson(id="l2", course_id="c2", title="数学课"), Lesson(id="fl", course_id="foreign", title="私有课")]); db.flush()
        db.get(ReviewCard, "r").status = "review"
        db.add_all([ReviewCard(id="new", course_id="c", lesson_id="l", title="未学习点", body="内容", status="new"),
                    ReviewCard(id="mastered", course_id="c2", lesson_id="l2", title="掌握点", body="内容", status="mastered"),
                    ReviewCard(id="secret", course_id="foreign", lesson_id="fl", title="秘密", body="秘密", status="review")]); db.commit()

    def test_filters_counts_pagination_and_no_write(self):
        with Session(self.engine) as db:
            self.seed(db)
            result = execute_tool(db, ToolContext("owner"), "list_knowledge_points", {"limit": 1})["data"]
            self.assertEqual(result["total"], 3)
            self.assertEqual(result["status_counts"], {"new": 1, "review": 1, "mastered": 1})
            self.assertEqual(result["next_offset"], 1)
            self.assertNotIn("秘密", json.dumps(result))
            filtered = execute_tool(db, ToolContext("owner", "c"), "list_knowledge_points", {"status": "review", "query": "知识"})["data"]
            self.assertEqual([row["id"] for row in filtered["items"]], ["r"])
            self.assertEqual(filtered["status_origin"], "user_marked")
            self.assertEqual(db.get(ReviewCard, "r").status, "review")
            json.dumps(filtered)

    def test_scope_invalid_arguments_and_recycled_records(self):
        with Session(self.engine) as db:
            self.seed(db)
            for args in ({"course_id": "c2"}, {"lesson_id": "l2"}, {"course_id": "foreign"}, {"lesson_id": "fl"}):
                result = execute_tool(db, ToolContext("owner", "c"), "list_knowledge_points", args)
                self.assertEqual(result["error"]["code"], "not_found")
            for args in ({"status": "due"}, {"username": "other"}, {"limit": True}):
                self.assertEqual(execute_tool(db, ToolContext("owner"), "list_knowledge_points", args)["error"]["code"], "invalid_arguments")
            self.assertEqual(execute_tool(db, ToolContext("owner"), "list_knowledge_points", {"course_id": "c", "lesson_id": "l2"})["error"]["code"], "not_found")
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assertEqual(execute_tool(db, ToolContext("owner", "c"), "list_knowledge_points", {})["data"]["total"], 0)

    @patch("app.modules.agent.loop.complete")
    def test_course_chat_records_real_statuses_steps_and_reload(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("list_knowledge_points", {"status": "review"}, "read"),
                {"role": "assistant", "content": '{"claims":[],"learning":{"query_ids":["L1"]},"answer":"已经全部掌握"}'}]
            result = send_message(db, chat["id"], "owner", "这门课哪些知识点需要复习", "r")
            reply = result["messages"][-1]
            self.assertIn("知识点（需要复习）：1 个", reply["content"])
            self.assertIn("状态由你手动标记", reply["content"])
            self.assertNotIn("已经全部掌握", reply["content"])
            self.assertNotIn("掌握点", reply["content"])
            self.assertEqual(reply["citations"], [])
            self.assertEqual(result["messages"][0]["steps"][0]["label"], "查询知识点状态")
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)

    @patch("app.modules.agent.loop.complete")
    def test_empty_result_is_verified_without_classroom_citations(self, model):
        with Session(self.engine) as db:
            model.side_effect = [call("list_knowledge_points", {"status": "mastered"}, "read"),
                {"role": "assistant", "content": '{"claims":[],"learning":{"query_ids":["L1"]}}'}]
            result = run_agent(db, ToolContext("owner", "c"), "哪些已掌握")
            self.assertEqual(result["outcome"], "answered")
            self.assertIn("没有符合条件的知识点", result["answer"])

    @patch("app.modules.agent.loop.complete")
    def test_answer_requeries_changed_status_instead_of_using_old_snapshot(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            def changed(*args, **kwargs):
                db.get(ReviewCard, "r").status = "mastered"; db.commit()
                return {"role": "assistant", "content": '{"claims":[],"learning":{"query_ids":["L1"]}}'}
            responses = iter([call("list_knowledge_points", {"status": "review"}, "read"), changed])
            model.side_effect = lambda *a, **kw: (value(*a, **kw) if callable(value := next(responses)) else value)
            self.assertIn("知识点（需要复习）：0 个", run_agent(db, ToolContext("owner", "c"), "哪些需要复习")["answer"])

    @patch("app.modules.agent.loop.complete")
    def test_invented_or_previous_query_is_rejected(self, model):
        with Session(self.engine) as db:
            model.return_value = {"role": "assistant", "content": '{"claims":[],"learning":{"query_ids":["L1"]}}'}
            with self.assertRaises(HTTPException) as error:
                run_agent(db, ToolContext("owner", "c"), "知识点状态")
            self.assertEqual(error.exception.status_code, 502)

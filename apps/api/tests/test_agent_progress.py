import json
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext
from app.shared.models import Lesson, LessonSummary, Course, now_utc
from test_course_progress import CourseProgressTest


class AgentProgressTest(unittest.TestCase):
    setUp = CourseProgressTest.setUp
    tearDown = CourseProgressTest.tearDown

    def test_counts_missing_states_paging_and_scope(self):
        with Session(self.engine) as db:
            context = ToolContext("owner", "course")
            result = execute_tool(db, context, "get_course_progress", {"limit": 1})
            self.assertTrue(result["ok"])
            data = result["data"]
            self.assertEqual(data["missing_summaries"]["total"], 2)
            self.assertEqual(data["missing_summaries"]["next_offset"], 1)
            self.assertEqual(data["review_cards"]["review"], 1)
            all_rows = execute_tool(db, context, "get_course_progress", {})["data"]["missing_summaries"]["items"]
            self.assertEqual({r["summary_status"] for r in all_rows}, {"queued", "failed"})
            self.assertFalse(execute_tool(db, context, "get_course_progress", {"course_id": "other-course"})["ok"])
            self.assertFalse(execute_tool(db, ToolContext("owner"), "get_course_progress", {})["ok"])
            db.get(Lesson, "lesson-3").deleted_at = now_utc(); db.commit()
            self.assertEqual(execute_tool(db, context, "get_course_progress", {})["data"]["missing_summaries"]["total"], 1)

    @patch("app.modules.agent.loop.complete")
    def test_final_uses_fresh_records_and_rejects_invented_query(self, model):
        with Session(self.engine) as db:
            def complete(*args, **kwargs):
                if complete.first:
                    complete.first = False
                    return {"role": "assistant", "content": None, "tool_calls": [{"id": "p", "type": "function",
                        "function": {"name": "get_course_progress", "arguments": "{}"}}]}
                summary = db.query(LessonSummary).filter_by(lesson_id="lesson-2").one()
                summary.status, summary.content = "completed", "新纪要"; db.commit()
                return {"content": json.dumps({"claims": [], "progress": {"query_ids": ["P1"]}})}
            complete.first = True
            model.side_effect = complete
            result = run_agent(db, ToolContext("owner", "course"), "哪些课次没有纪要，还有多少知识点需要复习")
            self.assertIn("需要复习 1 个", result["answer"])
            self.assertIn("缺少可用纪要的课次：1 节", result["answer"])
            self.assertIn("第三讲 · 生成失败", result["answer"])
            self.assertNotIn("第二讲 ·", result["answer"])
            model.side_effect = None
            model.return_value = {"content": '{"claims":[],"progress":{"query_ids":["P99"]}}'}
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                run_agent(db, ToolContext("owner", "course"), "查询进度")

    def test_missing_empty_stale_and_deleted_course(self):
        with Session(self.engine) as db:
            db.add(Lesson(id="missing", course_id="course", title="没有纪要")); db.flush()
            summary = db.query(LessonSummary).filter_by(lesson_id="lesson-1").one()
            summary.content = ""; db.commit()
            data = execute_tool(db, ToolContext("owner"), "get_course_progress", {"course_id": "course"})["data"]
            self.assertEqual(data["missing_summaries"]["total"], 4)
            db.get(Course, "course").deleted_at = now_utc(); db.commit()
            self.assertFalse(execute_tool(db, ToolContext("owner"), "get_course_progress", {"course_id": "course"})["ok"])

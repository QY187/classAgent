import json
import unittest
from unittest.mock import patch
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext
from app.shared.models import Course, Lesson, LessonSummary, ProcessingJob, Quiz, QuizAttempt
import test_home_overview as fixtures


class WorkflowTest(unittest.TestCase):
    setUp = fixtures.HomeOverviewTest.setUp
    tearDown = fixtures.HomeOverviewTest.tearDown

    def seed(self):
        self.db.add(Course(id="second", owner_id="u", name="另一门"))
        self.db.flush()
        self.db.add_all([Lesson(id="l", course_id="c", title="失败", status="failed"),
                         Lesson(id="s", course_id="second", title="待上传"),
                         Lesson(id="private", course_id="d", title="他人")])
        self.db.flush()
        self.db.add(ProcessingJob(lesson_id="l", stage="failed", error_message="真实失败"))
        self.db.commit()

    def test_pending_scope_pages_and_permissions(self):
        self.seed()
        result = execute_tool(self.db, ToolContext("owner"), "list_pending_lessons", {"limit": 1})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["total"], 2)
        self.assertTrue(result["data"]["has_more"])
        data = execute_tool(self.db, ToolContext("owner", "c"), "list_pending_lessons", {})["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["error_message"], "真实失败")
        self.assertFalse(execute_tool(self.db, ToolContext("owner", "c"), "list_pending_lessons", {"course_id":"second"})["ok"])
        self.assertFalse(execute_tool(self.db, ToolContext("owner"), "list_pending_lessons", {"limit": 51})["ok"])

    @patch("app.modules.agent.loop.complete")
    def test_pending_loop_refresh_and_fake_id(self, model):
        self.seed()
        def respond(*a, **kw):
            if respond.first:
                respond.first = False
                return {"role":"assistant", "tool_calls":[{"id":"r", "type":"function", "function":{"name":"list_pending_lessons", "arguments":"{}"}}]}
            lesson = self.db.get(Lesson, "l")
            lesson.status = "completed"
            self.db.add(LessonSummary(lesson_id="l", status="completed", content="可用纪要"))
            self.db.commit()
            return {"content":json.dumps({"claims":[], "workflow":{"query_ids":["W1"]}})}
        respond.first = True
        model.side_effect = respond
        result = run_agent(self.db, ToolContext("owner"), "哪些课没有处理完")
        self.assertEqual(result["outcome"], "answered")
        self.assertIn("共 1 节", result["answer"])
        self.assertNotIn("真实失败", result["answer"])
        model.side_effect = None
        model.return_value = {"content":'{"claims":[],"workflow":{"query_ids":["W99"]}}'}
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            run_agent(self.db, ToolContext("owner"), "哪些课没有处理完")

    def test_unanswered_excludes_submitted_drafts_and_others(self):
        self.seed()
        self.db.add_all([Quiz(id="q", course_id="c", title="未作答", status="ready"),
            Quiz(id="done", course_id="c", title="已提交", status="ready"),
            Quiz(id="draft", course_id="c", title="草稿", status="draft"),
            Quiz(id="privateq", course_id="d", title="他人", status="ready"),
            Quiz(id="secondq", course_id="second", title="另一门小测", status="ready")])
        self.db.flush()
        self.db.add_all([QuizAttempt(quiz_id="done", user_id="u", correct_count=1, total_count=1),
                        QuizAttempt(quiz_id="q", user_id="v", correct_count=1, total_count=1)])
        self.db.commit()
        result = execute_tool(self.db, ToolContext("owner"), "list_unanswered_quizzes", {"limit":1})
        self.assertEqual(result["data"]["total"], 2)
        self.assertTrue(result["data"]["has_more"])
        scoped = execute_tool(self.db, ToolContext("owner", "c"), "list_unanswered_quizzes", {})["data"]
        self.assertEqual([row["id"] for row in scoped["items"]], ["q"])
        self.assertNotIn("correct_option", json.dumps(scoped))
        self.assertFalse(execute_tool(self.db, ToolContext("owner", "c"), "list_unanswered_quizzes", {"course_id":"second"})["ok"])
        from app.modules.agent.workflow_queries import WorkflowQueryStore
        store = WorkflowQueryStore()
        store.collect("list_unanswered_quizzes", result)
        self.db.add(QuizAttempt(quiz_id="q", user_id="u", correct_count=0, total_count=1))
        self.db.commit()
        answer = store.answer(self.db, ToolContext("owner"), {"query_ids":["W1"]})
        self.assertIn("共 1 组", answer)
        self.assertNotIn("[未作答]", answer)

    def test_processing_details_no_job_and_stale_failure(self):
        self.seed()
        context = ToolContext("owner", "c")
        result = execute_tool(self.db, context, "get_processing_detail", {"lesson_id":"l"})
        self.assertEqual(result["data"]["error_message"], "真实失败")
        self.assertNotIn("object_key", result["data"])
        self.assertFalse(execute_tool(self.db, context, "get_processing_detail", {"lesson_id":"s"})["ok"])
        self.assertFalse(execute_tool(self.db, ToolContext("owner"), "get_processing_detail", {"lesson_id":"private"})["ok"])
        no_job = execute_tool(self.db, ToolContext("owner"), "get_processing_detail", {"lesson_id":"s"})["data"]
        self.assertIsNone(no_job["transcription_job"])
        self.db.get(Lesson, "l").status = "completed"
        self.db.add(LessonSummary(lesson_id="l", status="generating"))
        self.db.commit()
        current = execute_tool(self.db, context, "get_processing_detail", {"lesson_id":"l"})["data"]
        self.assertEqual(current["stage_label"], "正在生成纪要")
        self.assertIsNone(current["error_message"])
        self.assertIsNone(current["transcription_job"]["error_message"])

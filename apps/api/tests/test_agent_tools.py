import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.agent.executor import execute_tool
from app.modules.agent.registry import tool_schemas
from app.modules.agent.tools import ToolContext
from app.shared.models import Course, Lesson, LessonSummary, TranscriptSegment, User


class AgentToolTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(id="u1", username="owner", password_hash="private"),
                         User(id="u2", username="other", password_hash="private")])
        self.db.flush()
        self.db.add_all([Course(id="c1", owner_id="u1", name="数据结构"),
                         Course(id="c2", owner_id="u1", name="数学"),
                         Course(id="foreign", owner_id="u2", name="其他人的课")])
        self.db.flush()
        self.db.add_all([Lesson(id="l1", course_id="c1", title="第一讲", sort_order=1),
                         Lesson(id="l2", course_id="c1", title="第二讲", sort_order=0),
                         Lesson(id="l3", course_id="c2", title="数学课"),
                         Lesson(id="fl", course_id="foreign", title="私有课次")])
        self.db.flush()
        for lesson_id in ("l1", "l2", "l3", "fl"):
            self.db.add(TranscriptSegment(id=f"s-{lesson_id}", lesson_id=lesson_id,
                speaker="老师", start_ms=1000, end_ms=2000, text="二叉树每个节点最多两个孩子。"))
            self.db.add(LessonSummary(lesson_id=lesson_id, status="completed", content="课堂纪要内容"))
        self.db.commit()
        self.context = ToolContext("owner")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def call(self, name, args, context=None):
        return execute_tool(self.db, context or self.context, name, args)

    def test_schema_registry_and_strict_parameter_validation(self):
        schemas = tool_schemas()
        self.assertEqual(len(schemas), 7)
        for schema in schemas:
            self.assertFalse(schema["function"]["parameters"]["additionalProperties"])
            self.assertNotIn("username", schema["function"]["parameters"]["properties"])
        for args in ("not json", "[]", "x" * 16001, {"limit": "5"}, {"limit": True},
                     {"limit": 51}, {"offset": -1}, {"username": "other"}):
            result = self.call("list_courses", args)
            self.assertEqual(result["error"]["code"], "invalid_arguments")
        self.assertEqual(self.call("delete_course", {})["error"]["code"], "unknown_tool")
        self.assertEqual(self.call("search_course", {"course_id": "c1", "query": "   "})["error"]["code"], "invalid_arguments")
        self.assertTrue(self.call("list_courses", '{}')["ok"])

    def test_course_and_lesson_listing_respects_ownership_scope_and_order(self):
        result = self.call("list_courses", {"limit": 1})["data"]
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(len(self.call("list_courses", {"offset": 1})["data"]["items"]), 1)
        self.assertEqual(self.call("list_courses", {"query": "数据"})["data"]["items"][0]["id"], "c1")
        context = ToolContext("owner", "c1", "l1")
        self.assertEqual([row["id"] for row in self.call("list_courses", {}, context)["data"]["items"]], ["c1"])
        rows = self.call("list_lessons", {"course_id": "c1"})["data"]["items"]
        self.assertEqual([row["id"] for row in rows], ["l2", "l1"])
        self.assertEqual(self.call("list_lessons", {"course_id": "c1"}, context)["data"]["total"], 1)
        self.assertNotIn("password_hash", json.dumps(result))

    def test_all_tools_reject_foreign_and_out_of_scope_data(self):
        for name, args in (("list_lessons", {"course_id": "foreign"}),
                           ("get_transcript", {"lesson_id": "fl"}),
                           ("get_summary", {"lesson_id": "fl"}),
                           ("search_course", {"course_id": "foreign", "query": "二叉树"})):
            self.assertEqual(self.call(name, args)["error"]["code"], "not_found")
        context = ToolContext("owner", "c1", "l1")
        for name, args in (("list_lessons", {"course_id": "c2"}),
                           ("get_transcript", {"lesson_id": "l2"}),
                           ("get_summary", {"lesson_id": "l3"}),
                           ("search_course", {"course_id": "c1", "query": "二叉树", "lesson_id": "l2"}),
                           ("search_course", {"course_id": "c2", "query": "二叉树"})):
            self.assertEqual(self.call(name, args, context)["error"]["code"], "not_found")
        self.assertEqual(self.call("search_course", {"course_id": "c1", "lesson_id": "l3", "query": "二叉树"})["error"]["code"], "not_found")
        self.assertEqual(self.call("list_courses", {}, ToolContext("missing"))["error"]["code"], "unauthenticated")
        self.assertEqual(self.call("list_courses", {}, ToolContext("owner", lesson_id="l1"))["error"]["code"], "invalid_context")

    def test_transcript_pagination_preserves_sources_and_flags_truncation(self):
        self.db.add(TranscriptSegment(id="long", lesson_id="l1", speaker="老师", start_ms=3000,
                                     end_ms=4000, text="长" * 2500))
        self.db.commit()
        result = self.call("get_transcript", {"lesson_id": "l1", "limit": 1})
        self.assertEqual(result["content_trust"], "untrusted_classroom_data")
        data = result["data"]
        self.assertEqual((data["course_id"], data["lesson_id"], data["next_offset"]), ("c1", "l1", 1))
        self.assertEqual(data["items"][0]["segment_id"], "s-l1")
        self.assertEqual(data["items"][0]["start_ms"], 1000)
        tail = self.call("get_transcript", {"lesson_id": "l1", "offset": 1})["data"]
        self.assertTrue(tail["items"][0]["truncated"])
        self.assertEqual(len(tail["items"][0]["text"]), 2000)
        self.assertIsNone(tail["next_offset"])

    def test_summary_status_paging_and_missing_summary(self):
        first = self.call("get_summary", {"lesson_id": "l1", "limit": 2})["data"]
        self.assertTrue(first["available"])
        self.assertEqual((first["content"], first["next_offset"]), ("课堂", 2))
        self.assertEqual(self.call("get_summary", {"lesson_id": "l1", "offset": 2})["data"]["content"], "纪要内容")
        summary = self.db.query(LessonSummary).filter_by(lesson_id="l1").one()
        for status in ("stale", "queued", "processing", "failed"):
            summary.status = status
            self.db.commit()
            data = self.call("get_summary", {"lesson_id": "l1"})["data"]
            self.assertFalse(data["available"])
            self.assertEqual(data["content"], "")
        self.db.delete(summary); self.db.commit()
        self.assertEqual(self.call("get_summary", {"lesson_id": "l1"})["error"]["code"], "not_found")

    def test_search_applies_lesson_scope_before_limit_and_retains_sources(self):
        # 课程级搜索最多返回 30 段，指定课次必须在查询截断前过滤。
        self.db.add_all([TranscriptSegment(lesson_id="l1", speaker="老师", start_ms=i,
            end_ms=i+1, text="二叉树" ) for i in range(35)])
        self.db.commit()
        result = self.call("search_course", {"course_id": "c1", "query": "二叉树"}, ToolContext("owner", "c1", "l2"))["data"]
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["segment_id"], "s-l2")
        self.assertEqual(result["retrieval_method"], "keyword")
        self.assertFalse(result["has_more"])
        rows = self.call("search_course", {"course_id": "c1", "query": "二叉树", "limit": 2})["data"]
        self.assertEqual(len(rows["items"]), 2)
        self.assertTrue(rows["has_more"])

    def test_deleted_context_is_rejected_even_with_cached_objects(self):
        lesson = self.db.get(Lesson, "l1")
        lesson.deleted_at = datetime.now(timezone.utc); self.db.commit()
        for name, args in (("get_transcript", {"lesson_id": "l1"}), ("get_summary", {"lesson_id": "l1"})):
            self.assertEqual(self.call(name, args)["error"]["code"], "not_found")
        self.assertEqual(self.call("list_courses", {}, ToolContext("owner", "c1", "l1"))["error"]["code"], "not_found")
        self.assertEqual(self.call("list_lessons", {"course_id": "c1"})["data"]["total"], 1)
        self.db.get(Course, "c1").deleted_at = datetime.now(timezone.utc); self.db.commit()
        self.assertEqual(self.call("list_courses", {}, ToolContext("owner", "c1"))["error"]["code"], "not_found")

    def test_internal_failure_never_returns_exception_or_credentials(self):
        with patch("app.modules.agent.tools.courses.list_courses", side_effect=RuntimeError("secret_token database error")):
            result = self.call("list_courses", {})
        self.assertEqual(result["error"]["code"], "execution_failed")
        self.assertNotIn("secret_token", json.dumps(result))
        self.assertNotIn("data", result)


if __name__ == "__main__":
    unittest.main()

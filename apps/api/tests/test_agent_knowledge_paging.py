import unittest
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import ReviewCard, Lesson, now_utc
from app.modules.agent.tools import ToolContext
from app.modules.agent.executor import execute_tool


class KnowledgePagingTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def test_complete_body_and_missing_private_recycled_ids(self):
        with Session(self.engine) as db:
            body = "前文" * 450 + "关键结论在正文尾部。"
            db.get(ReviewCard,"r").body = body
            db.commit()
            context = ToolContext("owner","c")
            first = execute_tool(db, context,"list_knowledge_points",{"query":"关键结论"})["data"]["items"][0]
            self.assertEqual(len(first["body"]),600)
            self.assertTrue(first["body_truncated"])
            self.assertEqual(first["body_total_characters"],len(body))
            second = execute_tool(db,context,"list_knowledge_points",{"knowledge_point_id":"r","body_offset":first["next_body_offset"]})["data"]["items"][0]
            self.assertEqual(first["body"]+second["body"],body)
            self.assertIsNone(second["next_body_offset"])
            full = execute_tool(db,context,"list_knowledge_points",{"knowledge_point_id":"r","body_limit":4000})["data"]["items"][0]
            self.assertFalse(full["body_truncated"])
            self.assertEqual(full["body"],body)
            self.assertNotIn("source_excerpt",full)
            invalid = execute_tool(db,context,"list_knowledge_points",{"body_limit":4000})
            self.assertEqual(invalid["error"]["code"],"invalid_arguments")
            self.assertEqual(execute_tool(db,context,"list_knowledge_points",{"knowledge_point_id":"unknown"})["data"]["total"],0)
            db.get(Lesson,"l").deleted_at=now_utc();db.commit()
            self.assertEqual(execute_tool(db,context,"list_knowledge_points",{"knowledge_point_id":"r"})["data"]["total"],0)

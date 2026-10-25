import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import ReviewCard, AgentAction
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.knowledge_actions import status_request_issue


class MultiTargetStatusTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_multiple_targets_require_choice_before_any_write(self, model):
        with Session(self.engine) as db:
            chat=create_course_conversation(db,"c","owner")
            before=db.get(ReviewCard,"r").status
            result=send_message(db,chat["id"],"owner","把叶子节点标记为已掌握，再把前序遍历标记为未学习。","multi")
            model.assert_not_called()
            self.assertIn("只能修改一个",result["messages"][-1]["content"])
            self.assertEqual(db.get(ReviewCard,"r").status,before)
            self.assertEqual(db.query(AgentAction).count(),0)
            self.assertTrue(status_request_issue("把叶子节点标记为已掌握，再把叶子节点标记为未学习"))
            self.assertEqual(status_request_issue("把递归和迭代的区别标记为已掌握"),"")

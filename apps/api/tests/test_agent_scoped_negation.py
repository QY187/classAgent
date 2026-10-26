import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import ReviewCard,AgentAction
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.knowledge_actions import status_request
from test_agent_combined_actions import call


class ScopedNegationTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_only_separately_authorized_target_can_change(self,model):
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历"
            db.add(ReviewCard(id="leaf",course_id="c",lesson_id="l",title="叶子节点",body="没有孩子",status="new"));db.commit()
            chat=create_course_conversation(db,"c","owner")
            model.side_effect=[call("read","list_knowledge_points",{}),call("forbidden","update_knowledge_status",{"knowledge_point_id":"leaf","status":"mastered"}),
                call("allowed","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),{"content":"{}"}]
            result=send_message(db,chat["id"],"owner","不要修改叶子节点，把前序遍历标记为已掌握。","scoped")
            self.assertEqual(db.get(ReviewCard,"leaf").status,"new")
            self.assertEqual(db.get(ReviewCard,"r").status,"mastered")
            self.assertEqual(db.query(AgentAction).count(),1)
            self.assertIn("前序遍历",result["messages"][-1]["content"])
            for text in ["取消，把前序遍历标记为已掌握", "不要修改任何知识点，把前序遍历标记为已掌握", "不要修改前序遍历，把前序遍历标记为已掌握", "老师说不要修改叶子节点，把前序遍历标记为已掌握", "不要修改叶子节点，如何把前序遍历标记为已掌握？"]:
                self.assertIsNone(status_request(text),text)
            model.reset_mock()
            send_message(db,chat["id"],"owner","取消，把前序遍历标记为未学习","cancel")
            model.assert_not_called()
            self.assertEqual(db.get(ReviewCard,"r").status,"mastered")

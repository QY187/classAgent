import json
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import ReviewCard,Quiz,AgentAction
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message


def call(i,name,args):
    return {"role":"assistant","tool_calls":[{"id":i,"type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}


class CombinedActionTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_missing_query_is_continued_and_combined_with_receipt(self,model):
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历"
            db.get(Quiz,"q").status="ready";db.commit()
            chat=create_course_conversation(db,"c","owner")
            model.side_effect=[call("a","list_knowledge_points",{}),call("b","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                {"content":'{"claims":[],"outcome":"actions_completed"}'},call("c","list_unanswered_quizzes",{}),
                {"content":'{"claims":[],"outcome":"actions_completed","workflow":{"query_ids":["W1"]}}'}]
            result=send_message(db,chat["id"],"owner","把前序遍历标记为已掌握，同时列出还没做的小测","r")
            answer=result["messages"][-1]["content"]
            self.assertIn("已掌握",answer)
            self.assertIn("尚未提交作答的小测",answer)
            self.assertIn("小测]",answer)
            self.assertEqual(len(db.query(AgentAction).all()),1)

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

    @patch("app.modules.agent.loop.complete")
    def test_catalog_query_is_not_satisfied_by_narrow_target_lookup(self,model):
        from app.modules.chat.conversations import create_global_conversation
        from app.shared.models import Course
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历"
            db.add(Course(id="c2",owner_id="u",name="数学"));db.commit()
            chat=create_global_conversation(db,"owner")
            model.side_effect=[call("target","list_courses",{"query":"数据结构"}),call("read","list_knowledge_points",{"course_id":"c"}),
                call("write","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                {"content":'{"claims":[],"outcome":"actions_completed"}'},call("all","list_courses",{}),
                {"content":'{"claims":[],"outcome":"actions_completed"}'}]
            result=send_message(db,chat["id"],"owner","把数据结构课程的前序遍历标记为已掌握，同时列出所有课程。","catalog")
            self.assertIn("课程：数学",result["messages"][-1]["content"])
            self.assertEqual(db.query(AgentAction).count(),1)

    @patch("app.modules.agent.loop.complete")
    def test_multiple_query_categories_are_completed_or_explicitly_reported(self,model):
        from app.modules.agent.answers import requested_query_groups
        self.assertEqual(requested_query_groups("修改状态，同时查询课程进度和未作答小测"),{"progress","workflow"})
        self.assertEqual(requested_query_groups("修改状态，同时查询小测成绩"),{"quiz_results"})
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历";db.commit()
            chat=create_course_conversation(db,"c","owner")
            model.side_effect=[call("a","list_knowledge_points",{}),call("b","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                call("c","list_unanswered_quizzes",{}),{"content":'{"claims":[],"outcome":"actions_completed"}'},
                call("d","get_course_progress",{}),{"content":'{"claims":[],"outcome":"actions_completed"}'}]
            result=send_message(db,chat["id"],"owner","把前序遍历标记为已掌握，同时查询课程进度和未作答小测。","both")
            answer=result["messages"][-1]["content"]
            self.assertIn("课程进度",answer)
            self.assertIn("尚未提交作答的小测",answer)
            self.assertEqual(db.query(AgentAction).count(),1)

    def test_catalog_pagination_must_cover_from_first_to_last_page(self):
        from app.modules.agent.evidence import EvidenceStore
        store=EvidenceStore()
        store.catalog_reads=[("list_courses",{}, {"items":[],"next_offset":20})]
        self.assertFalse(store.catalog_complete({"list_courses"}))
        store.catalog_reads.append(("list_courses",{"offset":20},{"items":[],"next_offset":None}))
        self.assertTrue(store.catalog_complete({"list_courses"}))

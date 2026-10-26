import json
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import Course,Lesson,AgentAction
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.course_actions import resolve_course_request
from app.modules.chat.lesson_actions import resolve_lesson_request


def call(i,name,args):
    return {"role":"assistant","tool_calls":[{"id":i,"type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}


class CreationFollowupTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_name_supplement_preserves_and_executes_lesson_creation(self,model):
        with Session(self.engine) as db:
            chat=create_global_conversation(db,"owner")
            first=send_message(db,chat["id"],"owner","创建课程，再添加第三讲。","first")
            model.assert_not_called()
            self.assertIn("课程名称",first["messages"][-1]["content"])
            def create_lesson(*a,**k):
                created=next(row for row in db.query(Course).all() if row.name=="线性代数")
                return call("lesson","create_lesson",{"course_id":created.id,"title":"第三讲"})
            responses=iter([call("course","create_course",{"name":"线性代数"}),create_lesson,{"content":'{"claims":[],"outcome":"actions_completed"}'}])
            model.side_effect=lambda *a,**k:(v(*a,**k) if callable(v:=next(responses)) else v)
            result=send_message(db,chat["id"],"owner","线性代数","second")
            created=next(row for row in db.query(Course).all() if row.name=="线性代数")
            lessons=[row for row in db.query(Lesson).all() if row.course_id==created.id]
            self.assertEqual([row.title for row in lessons],["第三讲"])
            self.assertEqual(db.query(AgentAction).count(),2)
            self.assertIn("添加课次",result["messages"][-1]["content"])
            history=[{"role":"user","content":"创建课程，再添加第三讲。"},{"role":"assistant","content":"请提供课程名称？"}]
            self.assertIn("添加第三讲",resolve_course_request("线性代数",history))
            self.assertIn("添加第三讲",resolve_lesson_request("线性代数",history))
            self.assertEqual(resolve_lesson_request("取消",history),"取消")

    @patch("app.modules.agent.loop.complete")
    def test_global_missing_title_is_clarified_before_model_and_keeps_date(self,model):
        with Session(self.engine) as db:
            chat=create_global_conversation(db,"owner")
            send_message(db,chat["id"],"owner","在数据结构课程添加课次，日期为2026-10-05。","first")
            model.assert_not_called()
            model.side_effect=[call("find","list_courses",{"query":"数据结构"}),
                call("create","create_lesson",{"course_id":"c","title":"第三讲","lesson_date":"2026-10-05"}),{"content":"{}"}]
            send_message(db,chat["id"],"owner","第三讲","second")
            created=next(row for row in db.query(Lesson).all() if row.title=="第三讲")
            self.assertEqual(created.course_id,"c")
            self.assertEqual(created.lesson_date,"2026-10-05")

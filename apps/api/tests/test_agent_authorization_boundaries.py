import json
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
from sqlalchemy import select
import test_recycle_visibility as fixtures
from app.shared.models import ReviewCard, ChatMessage, Course, AgentAction
from app.modules.chat.conversations import create_course_conversation, create_global_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.knowledge_actions import status_request
from app.modules.chat.course_actions import resolve_course_request
from app.modules.chat.lesson_actions import resolve_lesson_request
from app.modules.chat.quiz_actions import wants_quiz


def call(name,args):
    return {"role":"assistant","tool_calls":[{"id":"forced","type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}


class AuthorizationBoundaryTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    def test_consult_negation_and_cancel_never_resume(self):
        for original in ["如何把知识点标记为已掌握？","不要把知识点标记为已掌握","把知识点标记为已掌握是什么意思？","把知识点标记为什么状态？"]:
            history=[{"role":"user","content":original},{"role":"assistant","content":"你想标记成哪种状态？"}]
            self.assertIsNone(status_request("已掌握",history))
        history=[{"role":"user","content":"创建课程"},{"role":"assistant","content":"课程名称是什么？"}]
        for reply in ["先别做","暂停","算了","停止","不要继续","取消"]:
            self.assertEqual(resolve_course_request(reply,history),reply)
            lesson_history=[{"role":"user","content":"添加课次"},history[-1]]
            self.assertEqual(resolve_lesson_request(reply,lesson_history),reply)
            self.assertFalse(wants_quiz(reply,[{"role":"user","content":"生成小测"},history[-1]]))

    def test_valid_missing_field_can_resume(self):
        history=[{"role":"user","content":"把前序遍历标记为"},{"role":"assistant","content":"要标记为哪种状态？"}]
        self.assertEqual(status_request("已掌握",history)["status"],"mastered")
        history=[{"role":"user","content":"创建课程"},{"role":"assistant","content":"课程名称是什么？"}]
        self.assertEqual(resolve_course_request("网络",history),"创建网络课程")

    @patch("app.modules.agent.loop.complete")
    def test_forced_model_cannot_write_after_consultation_or_cancel(self,model):
        with Session(self.engine) as db:
            for original,reply,global_scope,tool,args in [
                ("不要把知识点标记为已掌握","已掌握",False,"update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                ("如何把知识点标记为已掌握？","已掌握",False,"update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                ("创建课程","先别做",True,"create_course",{"name":"先别做"})]:
                chat=create_global_conversation(db,"owner") if global_scope else create_course_conversation(db,"c","owner")
                db.add_all([ChatMessage(conversation_id=chat["id"],position=1,request_id="old",role="user",status="completed",content=original),ChatMessage(conversation_id=chat["id"],position=2,request_id="old",role="assistant",status="completed",content="需要什么名称或状态？")]);db.commit()
                model.side_effect=[call(tool,args),{"content":'{"claims":[],"outcome":"needs_input","question":"请明确新的操作指令？"}'}]
                send_message(db,chat["id"],"owner",reply,"new")
                self.assertEqual(db.get(ReviewCard,"r").status,"new")
                self.assertFalse(any(row.name=="先别做" for row in db.scalars(select(Course))))
                self.assertFalse(db.scalars(select(AgentAction)).all())

import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from fastapi import HTTPException
from app.shared.models import Course
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.sending import send_message
from app.modules.agent.schemas import CreateCourseArguments
from test_agent_create_course import call


class CreateSemesterTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_explicit_semester_is_saved_and_invented_value_rejected(self, model):
        with Session(self.engine) as db:
            chat=create_global_conversation(db,"owner")
            model.side_effect=[call("create_course",{"name":"网络","semester":"2027秋"},"bad"),call("create_course",{"name":"网络","semester":"2026秋"},"good"),{"content":"{}"}]
            result=send_message(db,chat["id"],"owner","创建网络课程，学期为2026秋。","with")
            created=next(row for row in db.query(Course).all() if row.name=="网络")
            self.assertEqual(created.semester,"2026秋")
            self.assertIn("学期：2026秋",result["messages"][-1]["content"])
            model.side_effect=[call("create_course",{"name":"线性代数","semester":"2026秋"},"bad2"),call("create_course",{"name":"线性代数"},"good2"),{"content":"{}"}]
            send_message(db,chat["id"],"owner","创建线性代数课程","none")
            created=next(row for row in db.query(Course).all() if row.name=="线性代数")
            self.assertIsNone(created.semester)
            model.reset_mock()
            send_message(db,chat["id"],"owner","创建操作系统课程，学期为2026秋，学期为2027春。","ambiguous")
            model.assert_not_called()
            self.assertFalse(any(row.name=="操作系统" for row in db.query(Course).all()))

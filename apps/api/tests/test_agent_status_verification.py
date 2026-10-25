import unittest
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
import test_agent_knowledge_status as status_fixtures
from app.shared.models import ReviewCard, AgentAction
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.knowledge_actions import status_verification_hint


class StatusVerificationTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown
    seed = status_fixtures.KnowledgeStatusTest.seed
    responses = status_fixtures.KnowledgeStatusTest.responses

    @patch("app.modules.agent.loop.complete")
    def test_success_followup_reads_current_status_and_never_repeats_write(self, model):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db,"c","owner")
            model.side_effect=self.responses()
            send_message(db,chat["id"],"owner","把前序遍历标记为已掌握","write")
            self.assertEqual(db.get(ReviewCard,"r").status,"mastered")
            # 外部改回需要复习：核对必须反映当前状态，不能复述历史成功。
            db.get(ReviewCard,"r").status="review";db.commit()
            model.reset_mock()
            result=send_message(db,chat["id"],"owner","刚才修改成功了吗？","verify")
            model.assert_not_called()
            self.assertIn("需要复习",result["messages"][-1]["content"])
            self.assertEqual(db.get(ReviewCard,"r").status,"review")
            self.assertEqual(len(db.scalars(select(AgentAction)).all()),1)
            self.assertEqual(result["messages"][-2]["steps"][0]["label"],"查询知识点状态")
            for original in ["怎么把前序遍历标记为已掌握？", "不要把前序遍历标记为已掌握"]:
                self.assertEqual(status_verification_hint(db,"owner","c","刚才修改成功了吗？",[{"role":"user","content":original}]),{})

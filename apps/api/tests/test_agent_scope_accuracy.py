import json
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import Course, Lesson, TranscriptSegment
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext


class ScopeAccuracyTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_global_wrong_scope_response_is_repaired_and_can_switch(self,model):
        with Session(self.engine) as db:
            db.add(Course(id="math",owner_id="u",name="高等数学"));db.flush()
            db.add(Lesson(id="m",course_id="math",title="第一讲"));db.flush()
            db.add(TranscriptSegment(id="ms",lesson_id="m",start_ms=0,end_ms=1,text="导数是2x"));db.commit()
            model.side_effect=[{"content":'{"claims":[],"outcome":"needs_input","question":"请进入主对话或高等数学课程对话"}'},
                {"role":"assistant","tool_calls":[{"id":"read","type":"function","function":{"name":"get_transcript","arguments":'{"lesson_id":"m"}'}}]},
                {"content":'{"claims":[{"text":"导数是2x","source_ids":["E1"]}]}'}]
            result=run_agent(db,ToolContext("owner"),"高等数学课程的导数是多少",history=[{"role":"user","content":"数据结构课程讲了什么"},{"role":"assistant","content":"讲二叉树"}])
            self.assertEqual(result["outcome"],"answered")
            self.assertIn("2x",result["answer"])
            messages=model.call_args.args[0]
            self.assertTrue(any("当前是主对话" in item.get("content","") for item in messages))

    @patch("app.modules.agent.loop.complete")
    def test_course_cross_scope_uses_real_name_and_no_model(self,model):
        with Session(self.engine) as db:
            db.add(Course(id="math",owner_id="u",name="高等数学"));db.commit()
            result=run_agent(db,ToolContext("owner","c"),"高等数学课程的导数是什么")
            self.assertIn("数据结构",result["answer"])
            self.assertIn("高等数学",result["answer"])
            self.assertNotIn("不存在",result["answer"])
            self.assertEqual(result["outcome"],"needs_input")
            model.assert_not_called()

    def test_overlapping_names_use_longest_mention_but_keep_separate_mentions(self):
        from types import SimpleNamespace
        from app.modules.agent.loop import mentioned_courses
        courses = [SimpleNamespace(id="short",name="数学"),SimpleNamespace(id="long",name="高等数学")]
        self.assertEqual([r.id for r in mentioned_courses("高等数学课程里导数是什么",courses)],["long"])
        self.assertEqual([r.id for r in mentioned_courses("比较高等数学课程和数学课程",courses)],["long","short"])

    @patch("app.modules.agent.loop.complete")
    def test_current_long_course_name_is_not_blocked(self, model):
        with Session(self.engine) as db:
            db.add_all([Course(id="math",owner_id="u",name="高等数学"),Course(id="short",owner_id="u",name="数学")]);db.commit()
            model.return_value={"content":'{"claims":[],"outcome":"insufficient_evidence"}'}
            result=run_agent(db,ToolContext("owner","math"),"高等数学课程的内容是什么")
            model.assert_called_once()
            self.assertEqual(result["outcome"],"insufficient_evidence")

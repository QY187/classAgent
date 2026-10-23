import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import select
import test_home_overview as fixtures
from app.shared.models import Lesson, Course, ChatConversation, ChatMessage, AgentAction
from app.modules.chat.edit_actions import actions_for_message, edit_request
from app.modules.agent.schemas import UpdateLessonArguments, UpdateCourseArguments
from app.modules.agent.tools import ToolContext
from app.modules.agent.loop import run_agent


class EditTest(unittest.TestCase):
    setUp = fixtures.HomeOverviewTest.setUp
    tearDown = fixtures.HomeOverviewTest.tearDown

    def seed(self, text, course_id="c"):
        self.db.get(Course,"c").semester = "2026秋"
        self.db.add(Lesson(id="l", course_id="c", title="第三讲", lesson_date="2026-10-01", status="completed"))
        self.db.add(ChatConversation(id="chat", user_id="u", course_id=course_id, generation_token="token"))
        self.db.flush()
        self.db.add(ChatMessage(id="msg", conversation_id="chat", position=1, request_id="r", role="user", status="pending", content=text))
        self.db.commit()
        return actions_for_message(self.db, "chat", "owner", "msg", "token", text)

    def test_lesson_partial_fields_idempotency_and_parameter_tampering(self):
        text = "把第三讲改名为二叉树"
        action = self.seed(text)["update_lesson"]
        with self.assertRaises(HTTPException):
            action(UpdateLessonArguments(lesson_id="l", title="二叉树", lesson_date="2026-10-05"))
        args = UpdateLessonArguments(lesson_id="l", title="二叉树")
        result = action(args)
        self.assertEqual(result, action(args))
        self.assertEqual(self.db.get(Lesson,"l").lesson_date, "2026-10-01")
        self.assertEqual(self.db.get(Lesson,"l").status, "completed")
        self.assertEqual(len(self.db.scalars(select(AgentAction)).all()), 1)

    def test_course_rename_preserves_semester_and_duplicate_rejected(self):
        action = self.seed("把课程课程改名为新课程", None)["update_course"]
        result = action(UpdateCourseArguments(course_id="c",name="新课程"))
        self.assertEqual(self.db.get(Course,"c").semester,"2026秋")
        self.assertIn("课程名称：课程 → 新课程", result["message"])
        self.assertEqual(result, action(UpdateCourseArguments(course_id="c",name="新课程")))

    def test_dates_global_target_and_scope(self):
        text = "把课程课程的第三讲改名为二叉树，日期改为2026-10-05"
        action = self.seed(text, None)["update_lesson"]
        action(UpdateLessonArguments(lesson_id="l",title="二叉树",lesson_date="2026-10-05"))
        self.assertEqual(self.db.get(Lesson,"l").lesson_date,"2026-10-05")
        self.assertEqual(self.db.get(Lesson,"l").title,"二叉树")
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            UpdateLessonArguments(lesson_id="l",lesson_date="2026-02-30")
        for text in ["怎么把第三讲改名为二叉树", "不要把第三讲改名为二叉树", "如果把第三讲改名为二叉树", "老师说把第三讲改名为二叉树"]:
            self.assertIsNone(edit_request(text),text)

    def test_ambiguous_title_and_wrong_course_refused(self):
        action = self.seed("把第三讲的日期改为2026-10-05")["update_lesson"]
        self.db.add(Lesson(id="same",course_id="c",title="第三讲"))
        self.db.add(Lesson(id="private",course_id="d",title="第三讲"))
        self.db.commit()
        with self.assertRaises(HTTPException):
            action(UpdateLessonArguments(lesson_id="l",lesson_date="2026-10-05"))
        with self.assertRaises(HTTPException):
            action(UpdateLessonArguments(lesson_id="private",lesson_date="2026-10-05"))
        self.assertEqual(self.db.get(Lesson,"l").lesson_date,"2026-10-01")

    @patch("app.modules.agent.loop.complete")
    def test_model_loop_uses_real_receipt(self, model):
        text = "把第三讲改名为二叉树"
        actions = self.seed(text)
        def call(identity,name,args):
            return {"role":"assistant","tool_calls":[{"id":identity,"type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}
        model.side_effect = [call("lookup","list_lessons",{"course_id":"c"}),
            call("write","update_lesson",{"lesson_id":"l","title":"二叉树"}),
            {"content":'{"claims":[],"outcome":"actions_completed"}'}]
        result = run_agent(self.db,ToolContext("owner","c",actions=actions),text)
        self.assertEqual(result["outcome"],"actions_completed")
        self.assertIn("第三讲 → 二叉树",result["answer"])
        self.assertEqual(self.db.get(Lesson,"l").title,"二叉树")

    def test_duplicate_rename_and_date_without_year_are_not_written(self):
        action = self.seed("把第三讲改名为二叉树")["update_lesson"]
        self.db.add(Lesson(id="duplicate",course_id="c",title="二叉树"))
        self.db.commit()
        with self.assertRaises(HTTPException):
            action(UpdateLessonArguments(lesson_id="l",title="二叉树"))
        self.assertEqual(self.db.get(Lesson,"l").title,"第三讲")
        self.assertFalse(self.db.scalars(select(AgentAction)).all())
        self.db.get(ChatMessage,"msg").content = "把第三讲的日期改为10月5日"
        self.db.commit()
        action = actions_for_message(self.db,"chat","owner","msg","token","把第三讲的日期改为10月5日")["update_lesson"]
        with self.assertRaises(HTTPException):
            action(UpdateLessonArguments(lesson_id="l",lesson_date="2026-10-05"))
        self.assertEqual(self.db.get(Lesson,"l").lesson_date,"2026-10-01")

    def test_semester_only_preserves_course_name(self):
        action = self.seed("把课程课程的学期改为2027春",None)["update_course"]
        action(UpdateCourseArguments(course_id="c",semester="2027春"))
        self.assertEqual(self.db.get(Course,"c").name,"课程")
        self.assertEqual(self.db.get(Course,"c").semester,"2027春")

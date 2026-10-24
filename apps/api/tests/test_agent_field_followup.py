import unittest
from fastapi import HTTPException
from app.modules.chat.edit_actions import actions_for_message, resolve_edit_request
from app.modules.chat.lesson_actions import action_hint
from app.modules.agent.schemas import UpdateLessonArguments
from app.shared.models import Lesson
from test_agent_edits import EditTest


class FieldFollowupTest(EditTest):
    def test_year_followup_writes_original_target_and_only_date(self):
        text = "2026年"
        self.seed(text)
        history = [{"role":"user", "content":"把第三讲的日期改为10月5日"},
                   {"role":"assistant", "content":"请补充日期的年份？"}]
        action = actions_for_message(self.db,"chat","owner","msg","token",text,history)["update_lesson"]
        with self.assertRaises(HTTPException):
            action(UpdateLessonArguments(lesson_id="l",title="其他",lesson_date="2026-10-05"))
        action(UpdateLessonArguments(lesson_id="l",lesson_date="2026-10-05"))
        self.assertEqual(self.db.get(Lesson,"l").lesson_date,"2026-10-05")
        self.assertEqual(self.db.get(Lesson,"l").title,"第三讲")
        for origin in ["怎么把第三讲的日期改为10月5日", "不要把第三讲的日期改为10月5日"]:
            self.assertIsNone(resolve_edit_request(text,[{"role":"user","content":origin},history[-1]]))
        self.assertIsNone(resolve_edit_request("先别做",history))
        self.assertIsNone(resolve_edit_request("2026年",history[:-1]+[{"role":"assistant","content":"已修改成功。"}]))

    def test_lesson_title_followup_preserves_date_and_course(self):
        history = [{"role":"user","content":"在数据结构课程添加课次，日期为2026-10-05"},
                   {"role":"assistant","content":"请提供课次标题。"}]
        hint = action_hint("第三讲",history)
        self.assertEqual(hint["title"],"第三讲")
        self.assertEqual(hint["lesson_date"],"2026-10-05")
        self.assertEqual(action_hint("先别做",history),{})

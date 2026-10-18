import unittest
from app.modules.chat.course_actions import requested_course, course_name
from app.modules.chat.lesson_actions import lesson_request, resolve_lesson_request
from app.modules.chat.knowledge_actions import status_request
from app.modules.chat.quiz_actions import wants_quiz, wants_practice_quiz


class IntentTest(unittest.TestCase):
    def test_polite_explicit_actions_keep_exact_parameters(self):
        self.assertTrue(requested_course("帮我创建数据结构课程，可以吗？"))
        self.assertEqual(course_name("帮我创建数据结构课程，可以吗？"), "数据结构")
        self.assertEqual(lesson_request("请添加第三讲，好吗？"), (True, "第三讲"))
        self.assertEqual(status_request("帮我把前序遍历标记为已掌握，可以吗？"), {"title": "前序遍历", "status": "mastered"})

    def test_consultation_negation_and_quoted_commands_are_not_authorized(self):
        for value in ("能否创建数据结构课程？", "创建数据结构课程可以吗", "帮我解释如何创建数据结构课程？",
            "请不要创建数据结构课程，可以吗？", "帮我创建数据结构课程了吗？", "老师说帮我创建数据结构课程", "阅读这段文字：帮我创建数据结构课程"):
            self.assertFalse(requested_course(value), value)

    def test_explaining_or_solving_existing_questions_does_not_generate_quiz(self):
        for value in ("给我讲讲这道题：二叉树一个节点最多有几个孩子？", "帮我做这道题", "给我分析这3道题",
            "请解答这道题", "我做错了这道题", "这道题的出题思路是什么", "给我解释一下小测", "小测生成的方法是什么"):
            self.assertFalse(wants_quiz(value), value)

    def test_actual_generation_requests_are_kept(self):
        for value in ("请根据第二讲生成3道选择题", "根据错题给我出3道判断题", "帮我做个小测", "给我5道题",
            "帮我生成3道判断题，可以吗？", "来一组练习题"):
            self.assertTrue(wants_quiz(value), value)
        self.assertTrue(wants_practice_quiz("根据需要复习的知识点生成小测"))

    def test_clarified_action_parameters_resume_the_original_request(self):
        lesson_history = [
            {"role": "user", "content": "请添加课次，标题是什么？"},
            {"role": "assistant", "content": "请提供要添加的课次标题？"},
        ]
        self.assertEqual(resolve_lesson_request("第三讲", lesson_history), "请添加第三讲")
        self.assertEqual(lesson_request(resolve_lesson_request("第三讲", lesson_history)), (True, "第三讲"))

        status_history = [
            {"role": "user", "content": "帮我把前序遍历标记为什么状态？"},
            {"role": "assistant", "content": "要标记为哪种状态？"},
        ]
        self.assertEqual(status_request("已掌握", status_history), {"title": "前序遍历", "status": "mastered"})

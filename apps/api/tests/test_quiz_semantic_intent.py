import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app.modules.chat.quiz_actions import resolve_quiz_intent


class SemanticQuizIntentTest(unittest.TestCase):
    def test_screenshot_request_reaches_semantic_classifier(self):
        question = "去给我将测试课程的第二讲出5道题目"
        with patch("app.modules.agent.completion.complete", return_value={"content": '{"intent":"quiz"}'}) as model:
            self.assertEqual(resolve_quiz_intent(question), "quiz")
            self.assertIn(question, model.call_args.args[0][-1]["content"])
            self.assertEqual(model.call_args.args[1], [])

    def test_clear_request_needs_no_extra_model_call(self):
        with patch("app.modules.agent.completion.complete") as model:
            self.assertEqual(resolve_quiz_intent("给我生成5道判断题"), "quiz")
            model.assert_not_called()

    def test_semantic_decision_preserves_negative_and_existing_question_requests(self):
        for question in ("不要给第二讲出题", "你能出题吗？", "给我解答这道题", "老师说给第二讲出5道题"):
            with patch("app.modules.agent.completion.complete", return_value={"content": '{"intent":"none"}'}):
                self.assertEqual(resolve_quiz_intent(question), "none")

    def test_practice_decision_and_clarification_context(self):
        history = [{"role": "user", "content": "按错题考考我"}, {"role": "assistant", "content": "哪门课程？"}]
        with patch("app.modules.agent.completion.complete", return_value={"content": '{"intent":"practice"}'}) as model:
            self.assertEqual(resolve_quiz_intent("测试课程，考考我", history), "practice")
            self.assertIn("哪门课程", model.call_args.args[0][-1]["content"])

    def test_invalid_model_output_fails_before_authorizing_generation(self):
        for response in ('{"intent":"delete"}', '{}', 'true', 'not json', '{"intent":"quiz","extra":true}'):
            with patch("app.modules.agent.completion.complete", return_value={"content": response}):
                with self.assertRaises(HTTPException):
                    resolve_quiz_intent("去给我将测试课程的第二讲出5道题目")

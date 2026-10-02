import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.quizzes.service import _generate_questions, generate_quiz, get_quiz, publish_quiz, update_question
from app.modules.quizzes.schemas import QuizGenerate, QuizQuestionUpdate
from app.shared.models import Course, Lesson, TranscriptSegment, User


class QuizTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add_all([User(id="u1", username="owner", password_hash="x"), User(id="u2", username="other", password_hash="x")])
            db.flush()
            db.add(Course(id="c1", owner_id="u1", name="数据结构"))
            db.flush()
            db.add(Lesson(id="l1", course_id="c1", title="二叉树"))
            db.flush()
            db.add_all([TranscriptSegment(id=f"s{i}", lesson_id="l1", speaker="老师", start_ms=i * 1000,
                                          end_ms=i * 1000 + 900, text=f"第{i}层最多有两个的{i-1}次方个节点。") for i in range(1, 5)])
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_generation_checks_evidence_and_drops_unsupported_question(self):
        with Session(self.engine) as db:
            segments = db.query(TranscriptSegment).order_by(TranscriptSegment.start_ms).all()
            payload = {"questions": [
                {"kind": "true_false", "stem": f"第{i}层有上限吗？", "options": ["正确", "错误"],
                 "correct_option": 0, "explanation": "课堂原话给出上限", "source_index": i,
                 "evidence": segments[i - 1].text[:8]} for i in range(1, 4)
            ] + [{"kind": "true_false", "stem": "无来源题", "options": ["正确", "错误"],
                  "correct_option": 0, "explanation": "猜测", "source_index": 4, "evidence": "课堂记录中不存在"}]}
            response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": __import__("json").dumps(payload)}}]})
            with patch("app.modules.quizzes.service.get_settings", return_value=SimpleNamespace(deepseek_api_key="test", summary_model="test")), \
                 patch("app.modules.quizzes.service.httpx.post", return_value=response):
                questions = _generate_questions(segments, 5)
            self.assertEqual(len(questions), 3)
            self.assertEqual(questions[0]["source"].id, "s1")

    def test_draft_can_be_reviewed_and_published_without_exposing_answers(self):
        with Session(self.engine) as db:
            source = db.get(TranscriptSegment, "s1")
            generated = [{"kind": "true_false", "stem": f"判断题 {i}", "options": ["正确", "错误"],
                          "correct_option": 0, "explanation": "依据原文", "source": source, "evidence": source.text[:8]} for i in range(3)]
            with patch("app.modules.quizzes.service._generate_questions", return_value=generated):
                draft = generate_quiz(db, "c1", QuizGenerate(lesson_id="l1"), "owner")
            self.assertEqual(draft["status"], "draft")
            self.assertEqual(len(draft["questions"]), 3)
            self.assertIn("correct_option", draft["questions"][0])
            quiz_id = draft["id"]
            with self.assertRaises(HTTPException) as denied:
                get_quiz(db, quiz_id, "other")
            self.assertEqual(denied.exception.status_code, 404)
            changed = update_question(db, quiz_id, draft["questions"][0]["id"],
                                      QuizQuestionUpdate(stem="修改后的题目", options=["正确", "错误"], correct_option=1,
                                                         explanation="修改后的解析"), "owner")
            self.assertEqual(changed["questions"][0]["correct_option"], 1)
            ready = publish_quiz(db, quiz_id, "owner")
            self.assertEqual(ready["status"], "ready")
            self.assertNotIn("correct_option", ready["questions"][0])
            with self.assertRaises(HTTPException) as locked:
                update_question(db, quiz_id, draft["questions"][0]["id"],
                                QuizQuestionUpdate(stem="再改", options=["正确", "错误"], correct_option=0,
                                                   explanation="解析"), "owner")
            self.assertEqual(locked.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()

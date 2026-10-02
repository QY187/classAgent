import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.courses.service import get_course_progress
from app.shared.models import Course, Lesson, LessonSummary, Quiz, QuizAnswer, QuizAttempt, QuizQuestion, ReviewCard, TranscriptSegment, User


class CourseProgressTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add_all([
                User(id="owner", username="owner", password_hash="x"),
                User(id="other", username="other", password_hash="x"),
            ])
            db.flush()
            db.add_all([
                Course(id="course", owner_id="owner", name="数据结构"),
                Course(id="other-course", owner_id="other", name="其他课程"),
            ])
            db.flush()
            db.add_all([
                Lesson(id="lesson-1", course_id="course", title="第一讲"),
                Lesson(id="lesson-2", course_id="course", title="第二讲"),
                Lesson(id="lesson-3", course_id="course", title="第三讲"),
                Lesson(id="other-lesson", course_id="other-course", title="别人的课次"),
            ])
            db.flush()
            db.add_all([
                TranscriptSegment(lesson_id="lesson-1", start_ms=0, end_ms=1000, text="片段一"),
                TranscriptSegment(lesson_id="lesson-1", start_ms=1000, end_ms=2000, text="片段二"),
                TranscriptSegment(lesson_id="other-lesson", start_ms=0, end_ms=1000, text="其他片段"),
                LessonSummary(lesson_id="lesson-1", status="completed", content="有内容"),
                LessonSummary(lesson_id="lesson-2", status="queued", content=None),
                LessonSummary(lesson_id="lesson-3", status="failed", content="旧内容"),
                ReviewCard(id="r1", course_id="course", lesson_id="lesson-1", title="节点", body="定义", status="new"),
                ReviewCard(id="r2", course_id="course", lesson_id="lesson-1", title="边", body="定义", status="review"),
                ReviewCard(id="r3", course_id="course", lesson_id="lesson-2", title="树", body="定义", status="mastered"),
                ReviewCard(id="r4", course_id="other-course", lesson_id="other-lesson", title="其他", body="定义", status="new"),
            ])
            db.add_all([
                Quiz(id="quiz", course_id="course", title="二叉树小测"),
                Quiz(id="other-quiz", course_id="other-course", title="其他小测"),
            ])
            db.flush()
            db.add_all([
                QuizQuestion(id=question_id, quiz_id="quiz", position=position, kind="true_false", stem="判断", options_json="[]", correct_option=0, explanation="依据", source_start_ms=0, source_excerpt="原文")
                for position, question_id in enumerate(("q1", "q2"), start=1)
            ])
            db.add_all([
                QuizAttempt(id="attempt-1", quiz_id="quiz", user_id="owner", correct_count=1, total_count=2, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                QuizAttempt(id="attempt-2", quiz_id="quiz", user_id="owner", correct_count=2, total_count=2, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
                QuizAttempt(id="attempt-other-user", quiz_id="quiz", user_id="other", correct_count=0, total_count=2),
                QuizAttempt(id="attempt-other-course", quiz_id="other-quiz", user_id="other", correct_count=0, total_count=2),
            ])
            db.flush()
            db.add_all([
                QuizAnswer(attempt_id="attempt-1", question_id="q1", selected_option=1, is_correct=False),
                QuizAnswer(attempt_id="attempt-other-user", question_id="q1", selected_option=1, is_correct=False),
            ])
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_counts_distinct_lessons_and_ready_summaries(self):
        with Session(self.engine) as db:
            progress = get_course_progress(db, "course", "owner")
        self.assertEqual(progress["lesson_total"], 3)
        self.assertEqual(progress["transcript_lessons"], 1)
        self.assertEqual(progress["summary_lessons"], 1)
        self.assertEqual(progress["review_cards"], {"total": 3, "new": 1, "review": 1, "mastered": 1})
        self.assertEqual(progress["quizzes"]["attempt_count"], 2)
        self.assertEqual(progress["quizzes"]["average_score"], 75)
        self.assertEqual(progress["quizzes"]["wrong_question_count"], 1)
        self.assertEqual(progress["quizzes"]["recent_attempt"]["id"], "attempt-2")

    def test_other_users_course_is_hidden(self):
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as context:
                get_course_progress(db, "course", "other")
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

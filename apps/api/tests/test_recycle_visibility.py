import unittest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from app.core.db import Base
from app.core.visibility import visible_get
from app.shared.models import AudioFile, Course, CourseMaterial, Lesson, LessonSummary, Quiz, QuizQuestion, ReviewCard, TranscriptSegment, User, now_utc


class RecycleVisibilityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add(User(id="u", username="owner", password_hash="x")); db.flush()
            db.add(Course(id="c", owner_id="u", name="数据结构")); db.flush()
            db.add(Lesson(id="l", course_id="c", title="二叉树")); db.flush()
            db.add_all([
                TranscriptSegment(id="s", lesson_id="l", start_ms=0, end_ms=1, text="原文"),
                AudioFile(id="a", lesson_id="l", filename="a.mp3", content_type="audio/mpeg", object_key="a.mp3", size_bytes=1),
                CourseMaterial(id="m", course_id="c", lesson_id="l", filename="m.pdf", content_type="application/pdf", object_key="m.pdf", size_bytes=1),
                LessonSummary(id="sum", lesson_id="l", content="纪要"),
                ReviewCard(id="r", lesson_id="l", course_id="c", title="知识点", body="内容"),
            ])
            quiz = Quiz(id="q", course_id="c", lesson_id="l", title="小测")
            quiz.questions = [QuizQuestion(id="question", position=1, kind="true_false", stem="题目", options_json='["正确","错误"]', correct_option=0, explanation="解析", source_start_ms=0, source_excerpt="原文")]
            db.add(quiz); db.commit()

    def tearDown(self):
        self.engine.dispose()

    def assert_hidden(self, db, models):
        for model in models:
            self.assertEqual(list(db.scalars(select(model))), [], model.__name__)
            self.assertEqual(len(list(db.scalars(select(model).execution_options(include_deleted=True)))), 1)

    def test_course_hides_descendants_without_removing_any_data(self):
        with Session(self.engine) as db:
            course = db.get(Course, "c")
            course.deleted_at = now_utc(); db.commit()
            self.assert_hidden(db, [Course, Lesson, AudioFile, TranscriptSegment, CourseMaterial, LessonSummary, ReviewCard, Quiz, QuizQuestion])
            self.assertIsNone(visible_get(db, Course, "c"))
            self.assertIsNone(visible_get(db, Lesson, "l"))

    def test_lesson_hides_its_content_but_keeps_course(self):
        with Session(self.engine) as db:
            db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
            self.assert_hidden(db, [Lesson, AudioFile, TranscriptSegment, CourseMaterial, LessonSummary, ReviewCard, Quiz, QuizQuestion])
            self.assertIsNotNone(visible_get(db, Course, "c"))

    def test_material_hides_only_itself_and_restores_with_same_id(self):
        with Session(self.engine) as db:
            material = db.get(CourseMaterial, "m")
            material.deleted_at = now_utc(); db.commit()
            self.assert_hidden(db, [CourseMaterial])
            self.assertIsNotNone(visible_get(db, Lesson, "l"))
            material.deleted_at = None; db.commit()
            self.assertEqual(visible_get(db, CourseMaterial, "m").object_key, "m.pdf")

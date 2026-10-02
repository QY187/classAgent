import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from unittest.mock import patch

from app.core.db import Base
from app.modules.courses.service import create_lesson, delete_course, delete_lesson, list_lessons, reorder_lessons, update_course, update_lesson
from app.shared.models import AudioFile, Course, CourseMaterial, Lesson, LessonSummary, ReviewCard, TranscriptSegment, User
from app.shared.schemas import CourseUpdate, LessonCreate, LessonUpdate


class CourseManagementTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add_all([User(id="u1", username="owner", password_hash="x"), User(id="u2", username="other", password_hash="x")])
            db.flush()
            db.add(Course(id="c1", owner_id="u1", name="旧课程"))
            db.flush()
            db.add(Lesson(id="l1", course_id="c1", title="旧课次"))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_manual_order_survives_reload_and_new_lesson_goes_first(self):
        with Session(self.engine) as db:
            db.add(Lesson(id="l2", course_id="c1", title="第二讲"))
            db.commit()
            before = [lesson.id for lesson in list_lessons(db, "c1", "owner")]
            reordered = list(reversed(before))
            self.assertEqual([lesson.id for lesson in reorder_lessons(db, "c1", reordered, before, "owner")], reordered)
        with Session(self.engine) as db:
            self.assertEqual([lesson.id for lesson in list_lessons(db, "c1", "owner")], reordered)
            new = create_lesson(db, "c1", LessonCreate(title="新课次"), "owner")
            self.assertEqual([lesson.id for lesson in list_lessons(db, "c1", "owner")], [new.id, *reordered])

    def test_reorder_rejects_other_user_duplicates_and_changed_list(self):
        with Session(self.engine) as db:
            for ids, expected, username, status in (
                (["l1"], ["l1"], "other", 404),
                (["l1", "l1"], ["l1"], "owner", 400),
                (["unknown"], ["l1"], "owner", 409),
                (["l1"], [], "owner", 409),
            ):
                with self.assertRaises(HTTPException) as denied:
                    reorder_lessons(db, "c1", ids, expected, username)
                self.assertEqual(denied.exception.status_code, status)
                db.rollback()
            self.assertIsNone(db.get(Lesson, "l1").sort_order)

    def test_edit_course_and_lesson_without_changing_ids(self):
        with Session(self.engine) as db:
            course = update_course(db, "c1", CourseUpdate(name="  数据结构  ", semester=" 2026 秋 "), "owner")
            lesson = update_lesson(db, "l1", LessonUpdate(title=" 二叉树 ", lesson_date="2026-10-02"), "owner")
            self.assertEqual((course.id, course.name, course.semester), ("c1", "数据结构", "2026 秋"))
            self.assertEqual((lesson.id, lesson.course_id, lesson.title, lesson.lesson_date), ("l1", "c1", "二叉树", "2026-10-02"))

    def test_other_user_cannot_edit(self):
        with Session(self.engine) as db:
            for action in (
                lambda: update_course(db, "c1", CourseUpdate(name="改名"), "other"),
                lambda: update_lesson(db, "l1", LessonUpdate(title="改名"), "other"),
            ):
                with self.assertRaises(HTTPException) as denied:
                    action()
                self.assertEqual(denied.exception.status_code, 404)
            self.assertEqual(db.get(Course, "c1").name, "旧课程")
            self.assertEqual(db.get(Lesson, "l1").title, "旧课次")

    def test_delete_lesson_hides_content_and_preserves_files(self):
        with Session(self.engine) as db:
            db.add_all([
                AudioFile(id="a1", lesson_id="l1", filename="课堂.mp3", content_type="audio/mpeg", object_key="lessons/l1/a1.mp3", size_bytes=4),
                CourseMaterial(id="m1", course_id="c1", lesson_id="l1", filename="课件.pdf", content_type="application/pdf", object_key="materials/c1/m1.pdf", size_bytes=4),
                TranscriptSegment(id="s1", lesson_id="l1", speaker="说话人 1", start_ms=0, end_ms=1000, text="内容"),
                LessonSummary(id="sum1", lesson_id="l1", status="completed"),
                ReviewCard(id="r1", course_id="c1", lesson_id="l1", title="概念", body="内容"),
            ])
            db.commit()
            with patch("app.infrastructure.storage.delete_file") as storage:
                with self.assertRaises(HTTPException) as denied:
                    delete_lesson(db, "l1", "other")
                self.assertEqual(denied.exception.status_code, 404)
                storage.assert_not_called()
                delete_lesson(db, "l1", "owner")
                storage.assert_not_called()
            for model, row_id in ((Lesson, "l1"), (AudioFile, "a1"), (CourseMaterial, "m1"),
                                  (TranscriptSegment, "s1"), (LessonSummary, "sum1"), (ReviewCard, "r1")):
                self.assertIsNone(db.scalar(select(model).where(model.id == row_id)))
                self.assertIsNotNone(db.scalar(select(model).where(model.id == row_id).execution_options(include_deleted=True)))
            self.assertIsNotNone(db.get(Course, "c1"))

    def test_delete_course_hides_lessons_and_rejects_active_processing(self):
        with Session(self.engine) as db:
            db.add(CourseMaterial(id="m2", course_id="c1", lesson_id=None, filename="资料.pdf", content_type="application/pdf", object_key="materials/c1/m2.pdf", size_bytes=4))
            db.commit()
            with patch("app.infrastructure.storage.delete_file") as storage:
                with self.assertRaises(HTTPException) as denied:
                    delete_course(db, "c1", "other")
                self.assertEqual(denied.exception.status_code, 404)
                lesson = db.get(Lesson, "l1")
                lesson.status = "transcribing"
                db.commit()
                with self.assertRaises(HTTPException) as busy:
                    delete_course(db, "c1", "owner")
                self.assertEqual(busy.exception.status_code, 409)
                storage.assert_not_called()
                lesson.status = "completed"
                db.commit()
                delete_course(db, "c1", "owner")
                storage.assert_not_called()
            self.assertIsNone(db.get(Course, "c1"))
            self.assertIsNone(db.get(Lesson, "l1"))
            self.assertIsNone(db.get(CourseMaterial, "m2"))

    def test_move_to_bin_does_not_depend_on_storage(self):
        with Session(self.engine) as db:
            db.add(CourseMaterial(id="m3", course_id="c1", filename="资料.pdf", content_type="application/pdf", object_key="materials/c1/m3.pdf", size_bytes=4))
            db.commit()
            with patch("app.infrastructure.storage.delete_file", side_effect=OSError("storage unavailable")):
                delete_course(db, "c1", "owner")
            self.assertIsNotNone(db.scalar(select(Course).execution_options(include_deleted=True)))
            self.assertIsNotNone(db.scalar(select(CourseMaterial).execution_options(include_deleted=True)))


if __name__ == "__main__":
    unittest.main()

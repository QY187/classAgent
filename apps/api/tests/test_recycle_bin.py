from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_recycle_visibility import RecycleVisibilityTest
from app.modules.recycle_bin.queries import list_items
from app.modules.recycle_bin.service import move_to_bin
from app.modules.recycle_bin.restore import restore_item
from app.modules.recycle_bin.purge import purge_item
from app.modules.recycle_bin.mapper import raw_get
from app.modules.recycle_bin.file_cleanup import clean_pending_files
from unittest.mock import patch
from app.core.visibility import visible_get
from app.shared.models import AudioFile, Course, CourseMaterial, Lesson, LessonSummary, Quiz, QuizQuestion, User


class RecycleBinTest(RecycleVisibilityTest):
    def test_queued_processing_cannot_be_recycled_and_lost(self):
        with Session(self.engine) as db:
            for model, identity, status in [(Lesson, "l", "queued"), (LessonSummary, "sum", "queued")]:
                item = visible_get(db, model, identity)
                old_status = item.status
                item.status = status; db.commit()
                with self.assertRaises(HTTPException) as blocked:
                    move_to_bin(db, "course", "c", "owner")
                self.assertEqual(blocked.exception.status_code, 409); db.rollback()
                item.status = old_status; db.commit()
            self.assertIsNotNone(visible_get(db, Course, "c"))
    def test_purge_deletes_descendants_and_preserves_other_courses(self):
        with Session(self.engine) as db:
            db.add(Course(id="keep", owner_id="u", name="保留")); db.commit()
            move_to_bin(db, "course", "c", "owner")
            with patch("app.modules.recycle_bin.file_cleanup.delete_file") as storage:
                self.assertEqual(purge_item(db, "course", "c", "owner"), {"cleaned": 2, "pending": 0})
                self.assertEqual({call.args[0] for call in storage.call_args_list}, {"a.mp3", "m.pdf"})
            for model, identity in [(Course, "c"), (Lesson, "l"), (CourseMaterial, "m"), (Quiz, "q"), (QuizQuestion, "question")]:
                self.assertIsNone(raw_get(db, model, identity))
            self.assertIsNotNone(visible_get(db, Course, "keep"))

    def test_purge_lesson_removes_its_materials_without_orphans(self):
        with Session(self.engine) as db:
            move_to_bin(db, "lesson", "l", "owner")
            with patch("app.modules.recycle_bin.file_cleanup.delete_file"):
                purge_item(db, "lesson", "l", "owner")
            self.assertIsNone(raw_get(db, CourseMaterial, "m"))
            self.assertIsNotNone(visible_get(db, Course, "c"))

    def test_purge_rejects_active_content_and_retains_failed_cleanup_for_retry(self):
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as active:
                purge_item(db, "course", "c", "owner")
            self.assertEqual(active.exception.status_code, 409); db.rollback()
            move_to_bin(db, "material", "m", "owner")
            with patch("app.modules.recycle_bin.file_cleanup.delete_file", side_effect=OSError("unavailable")), patch("app.modules.recycle_bin.file_cleanup.logger.warning"):
                self.assertEqual(purge_item(db, "material", "m", "owner"), {"cleaned": 0, "pending": 1})
            self.assertIsNone(raw_get(db, CourseMaterial, "m"))
            with patch("app.modules.recycle_bin.file_cleanup.delete_file") as storage:
                self.assertEqual(clean_pending_files(db, "owner"), {"cleaned": 1, "pending": 0})
                storage.assert_called_once_with("m.pdf")

    def test_restore_preserves_individual_deletions_ids_and_files(self):
        with Session(self.engine) as db:
            move_to_bin(db, "material", "m", "owner")
            move_to_bin(db, "lesson", "l", "owner")
            move_to_bin(db, "course", "c", "owner")
            with self.assertRaises(HTTPException) as blocked:
                restore_item(db, "lesson", "l", "owner")
            self.assertEqual(blocked.exception.status_code, 409); db.rollback()
            restore_item(db, "course", "c", "owner")
            self.assertIsNotNone(visible_get(db, Course, "c"))
            self.assertIsNone(visible_get(db, Lesson, "l"))
            self.assertEqual(list_items(db, "owner")[0]["kind"], "lesson")
            with self.assertRaises(HTTPException) as blocked:
                restore_item(db, "material", "m", "owner")
            self.assertEqual(blocked.exception.status_code, 409); db.rollback()
            restore_item(db, "lesson", "l", "owner")
            self.assertEqual(visible_get(db, AudioFile, "a").object_key, "a.mp3")
            self.assertIsNone(visible_get(db, CourseMaterial, "m"))
            restore_item(db, "material", "m", "owner")
            self.assertEqual(visible_get(db, CourseMaterial, "m").object_key, "m.pdf")
            self.assertEqual(list_items(db, "owner"), [])
            with self.assertRaises(HTTPException) as repeated:
                restore_item(db, "course", "c", "owner")
            self.assertEqual(repeated.exception.status_code, 409)

    def test_restore_denies_other_account(self):
        with Session(self.engine) as db:
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            move_to_bin(db, "course", "c", "owner")
            with self.assertRaises(HTTPException) as denied:
                restore_item(db, "course", "c", "other")
            self.assertEqual(denied.exception.status_code, 404)

    def test_list_groups_under_deleted_parent_and_isolates_owner(self):
        with Session(self.engine) as db:
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            move_to_bin(db, "material", "m", "owner")
            self.assertEqual([(i["kind"], i["id"]) for i in list_items(db, "owner")], [("material", "m")])
            move_to_bin(db, "lesson", "l", "owner")
            self.assertEqual([(i["kind"], i["id"]) for i in list_items(db, "owner")], [("lesson", "l")])
            move_to_bin(db, "course", "c", "owner")
            self.assertEqual([(i["kind"], i["id"]) for i in list_items(db, "owner")], [("course", "c")])
            self.assertEqual(list_items(db, "other"), [])

    def test_move_rejects_invalid_owner_kind_and_repeated_deletion(self):
        with Session(self.engine) as db:
            db.add(User(id="other", username="other", password_hash="x")); db.commit()
            for kind, identity, username in [("course", "c", "other"), ("invalid", "c", "owner"), ("lesson", "missing", "owner")]:
                with self.assertRaises(HTTPException) as denied:
                    move_to_bin(db, kind, identity, username)
                self.assertEqual(denied.exception.status_code, 404)
                db.rollback()
            move_to_bin(db, "course", "c", "owner")
            for kind, identity in [("course", "c"), ("lesson", "l"), ("material", "m")]:
                with self.assertRaises(HTTPException) as denied:
                    move_to_bin(db, kind, identity, "owner")
                self.assertEqual(denied.exception.status_code, 404)
                db.rollback()

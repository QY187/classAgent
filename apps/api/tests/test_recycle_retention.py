from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_recycle_visibility import RecycleVisibilityTest
from app.shared.models import Course, Lesson, CourseMaterial, PendingFileDeletion
from app.modules.recycle_bin.mapper import raw_get
from app.modules.recycle_bin.retention import expires_at, is_expired
from app.modules.recycle_bin.expiration import remove_expired_items
from app.modules.recycle_bin.restore import restore_item


class RetentionTest(RecycleVisibilityTest):
    def test_exact_boundary(self):
        deleted = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(is_expired(deleted, deleted + timedelta(days=30, microseconds=-1)))
        self.assertTrue(is_expired(deleted, deleted + timedelta(days=30)))
        self.assertEqual(expires_at(deleted.replace(tzinfo=None)), expires_at(deleted))

    @patch("app.modules.recycle_bin.file_cleanup.delete_file")
    def test_course_expiration_cascades(self, storage):
        now = datetime.now(timezone.utc)
        with Session(self.engine) as db:
            db.get(Course, "c").deleted_at = now - timedelta(days=30); db.commit()
            result = remove_expired_items(db, now)
            self.assertEqual(result["removed"], 1)
            self.assertIsNone(raw_get(db, Course, "c"))
            self.assertIsNone(raw_get(db, Lesson, "l"))
            self.assertIsNone(raw_get(db, CourseMaterial, "m"))
            self.assertEqual(storage.call_count, 2)

    @patch("app.modules.recycle_bin.file_cleanup.delete_file")
    def test_hidden_child_expires_independently(self, storage):
        now = datetime.now(timezone.utc)
        with Session(self.engine) as db:
            db.get(CourseMaterial, "m").deleted_at = now - timedelta(days=30)
            db.get(Course, "c").deleted_at = now - timedelta(days=1); db.commit()
            self.assertEqual(remove_expired_items(db, now)["removed"], 1)
            self.assertIsNotNone(raw_get(db, Course, "c"))
            self.assertIsNone(raw_get(db, CourseMaterial, "m"))

    def test_expired_restore_blocked_and_active_records_kept(self):
        with Session(self.engine) as db:
            db.get(CourseMaterial, "m").deleted_at = datetime.now(timezone.utc) - timedelta(days=31); db.commit()
            with self.assertRaises(HTTPException) as caught:
                restore_item(db, "material", "m", "owner")
            self.assertEqual(caught.exception.status_code, 409)
            db.rollback()
            raw_get(db, CourseMaterial, "m").deleted_at = None; db.commit()
            self.assertEqual(remove_expired_items(db)["removed"], 0)

    @patch("app.modules.recycle_bin.file_cleanup.delete_file")
    def test_file_retry_without_expired_items(self, storage):
        with Session(self.engine) as db:
            db.add(PendingFileDeletion(user_id="u", object_key="retry.pdf")); db.commit()
            storage.side_effect = OSError("storage unavailable")
            self.assertEqual(remove_expired_items(db)["cleaned"], 0)
            storage.side_effect = None
            self.assertEqual(remove_expired_items(db)["cleaned"], 1)


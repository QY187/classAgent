import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.db import Base
from app.modules.recycle_bin.file_cleanup import clean_pending_files, pending_count
from app.shared.models import PendingFileDeletion, User


class FileCleanupTest(unittest.TestCase):
    def test_failure_is_retryable_and_other_accounts_are_untouched(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add_all([User(id="u1", username="owner", password_hash="x"), User(id="u2", username="other", password_hash="x")]); db.flush()
            db.add_all([PendingFileDeletion(user_id="u1", object_key="own.pdf"), PendingFileDeletion(user_id="u2", object_key="other.pdf")]); db.commit()
            with patch("app.modules.recycle_bin.file_cleanup.delete_file", side_effect=OSError("unavailable")), patch("app.modules.recycle_bin.file_cleanup.logger.warning"):
                self.assertEqual(clean_pending_files(db, "owner"), {"cleaned": 0, "pending": 1})
            with patch("app.modules.recycle_bin.file_cleanup.delete_file") as storage:
                self.assertEqual(clean_pending_files(db, "owner"), {"cleaned": 1, "pending": 0})
                storage.assert_called_once_with("own.pdf")
                self.assertEqual(clean_pending_files(db, "owner"), {"cleaned": 0, "pending": 0})
            self.assertEqual(pending_count(db, "other"), 1)
        engine.dispose()

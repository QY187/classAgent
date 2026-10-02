from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_recycle_visibility import RecycleVisibilityTest
from app.modules.recycle_bin.queries import list_items
from app.modules.recycle_bin.service import move_to_bin
from app.modules.recycle_bin.restore import restore_item
from app.core.visibility import visible_get
from app.shared.models import AudioFile, Course, CourseMaterial, Lesson, User


class RecycleBinTest(RecycleVisibilityTest):
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

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.passwords import hash_password, verify_password
from app.core.deps import _resolve
from app.modules.auth.service import change_password, change_username, issue_access_token, save_avatar
from app.modules.courses.service import list_courses
from app.main import _seed_root_user, app
from app.shared.models import Course, User


class AccountSettingsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        User.__table__.create(self.engine)
        Course.__table__.create(self.engine)
        with Session(self.engine) as db:
            db.add(User(id="student-id", username="student", password_hash=hash_password("old-password")))
            db.add(Course(owner_id="student-id", owner_username="student", name="数据结构"))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_wrong_current_password_does_not_change_password(self):
        with Session(self.engine) as db, patch("app.modules.auth.service.revoke_all_for_user") as revoke:
            with self.assertRaises(HTTPException) as error:
                change_password(db, "student", "wrong-password", "new-password")
            self.assertEqual(error.exception.status_code, 400)
            revoke.assert_not_called()
            user = db.scalar(select(User).where(User.username == "student"))
            self.assertTrue(verify_password("old-password", user.password_hash))

    def test_change_password_revokes_refresh_sessions(self):
        with Session(self.engine) as db, patch("app.modules.auth.service.revoke_all_for_user") as revoke:
            change_password(db, "student", "old-password", "new-password")
            revoke.assert_called_once_with("student-id")
            db.expire_all()
            user = db.scalar(select(User).where(User.username == "student"))
            self.assertFalse(verify_password("old-password", user.password_hash))
            self.assertTrue(verify_password("new-password", user.password_hash))

    def test_rename_keeps_course_ownership_by_user_id(self):
        with Session(self.engine) as db, patch("app.modules.auth.service.revoke_all_for_user") as revoke:
            change_username(db, "student", "old-password", "new_student")
            revoke.assert_called_once_with("student-id")
            db.expire_all()
            user = db.scalar(select(User).where(User.username == "new_student"))
            self.assertEqual(user.id, "student-id")
            self.assertEqual([course.name for course in list_courses(db, "new_student")], ["数据结构"])
            self.assertEqual(db.scalar(select(Course)).owner_id, "student-id")
            with self.assertRaises(HTTPException) as expired:
                list_courses(db, "student")
            self.assertEqual(expired.exception.status_code, 401)

    def test_renamed_initial_account_is_not_recreated_on_startup(self):
        with Session(self.engine) as db, patch("app.modules.auth.service.revoke_all_for_user"):
            change_username(db, "student", "old-password", "new_student")
        with patch("app.main.SessionLocal", sessionmaker(bind=self.engine)), patch(
            "app.main.get_settings", return_value=SimpleNamespace(admin_username="student", admin_password="initial-password")
        ):
            _seed_root_user()
        with Session(self.engine) as db:
            self.assertEqual(db.scalars(select(User.username)).all(), ["new_student"])

    def test_access_token_uses_stable_user_id_after_rename(self):
        stable_token = issue_access_token("student-id")
        legacy_token = issue_access_token("student")
        with Session(self.engine) as db, patch("app.modules.auth.service.revoke_all_for_user"):
            change_username(db, "student", "old-password", "new_student")
            self.assertEqual(_resolve(stable_token, db), "new_student")
            with self.assertRaises(HTTPException) as expired:
                _resolve(legacy_token, db)
            self.assertEqual(expired.exception.status_code, 401)

    def test_rename_requires_password_and_unique_name(self):
        with Session(self.engine) as db, patch("app.modules.auth.service.revoke_all_for_user") as revoke:
            db.add(User(username="taken", password_hash="test"))
            db.commit()
            for password, name, status in [("wrong", "new_name", 400), ("old-password", "taken", 409)]:
                with self.assertRaises(HTTPException) as error:
                    change_username(db, "student", password, name)
                self.assertEqual(error.exception.status_code, status)
            revoke.assert_not_called()

    def test_avatar_upload_validates_file_and_keeps_user_identity(self):
        image = b"\x89PNG\r\n\x1a\n" + b"image-data"
        with Session(self.engine) as db, patch("app.modules.auth.service.upload_file") as upload:
            with self.assertRaises(HTTPException) as invalid:
                save_avatar(db, "student", b"<svg>not an accepted avatar</svg>")
            self.assertEqual(invalid.exception.status_code, 400)
            with self.assertRaises(HTTPException) as oversized:
                save_avatar(db, "student", image + b"0" * (2 * 1024 * 1024))
            self.assertEqual(oversized.exception.status_code, 400)
            upload.assert_not_called()

            user = save_avatar(db, "student", image)
            upload.assert_called_once()
            self.assertEqual(upload.call_args.args[0], "avatars/student-id")
            self.assertEqual(user.avatar_content_type, "image/png")
            self.assertEqual(user.id, "student-id")


class AvatarApiTest(unittest.TestCase):
    def test_upload_and_read_avatar_require_own_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        User.__table__.create(engine)
        with Session(engine) as db:
            db.add_all([User(id="avatar-user", username="avatar_user", password_hash="test"), User(id="other-user", username="other_user", password_hash="test")])
            db.commit()

        def test_db():
            with Session(engine) as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        image = b"\x89PNG\r\n\x1a\n" + b"image-data"
        with TemporaryDirectory() as directory:
            avatar_path = Path(directory) / "avatar"

            def store_avatar(_key, stream, _size, _content_type):
                avatar_path.write_bytes(stream.read())

            try:
                with patch("app.modules.auth.service.upload_file", side_effect=store_avatar), patch(
                    "app.modules.auth.controller.materialize_file", return_value=(avatar_path, False)
                ):
                    client = TestClient(app)
                    self.assertEqual(client.get("/auth/avatar").status_code, 401)
                    headers = {"Authorization": f"Bearer {issue_access_token('avatar-user')}"}
                    other_headers = {"Authorization": f"Bearer {issue_access_token('other-user')}"}
                    self.assertEqual(client.get("/auth/avatar", headers=headers).status_code, 404)
                    response = client.post("/auth/avatar", headers=headers, files={"file": ("avatar.png", image, "image/png")})
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()["has_avatar"])
                    self.assertTrue(client.get("/auth/me", headers=headers).json()["has_avatar"])
                    served = client.get("/auth/avatar", headers=headers)
                    self.assertEqual((served.status_code, served.headers["content-type"], served.content), (200, "image/png", image))
                    self.assertEqual(client.get("/auth/avatar", headers=other_headers).status_code, 404)
            finally:
                app.dependency_overrides.pop(get_db, None)
                engine.dispose()


if __name__ == "__main__":
    unittest.main()

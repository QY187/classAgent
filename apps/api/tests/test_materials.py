import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.modules.materials.service import cleanup_converted_preview, convert_office_to_pdf, get_material_file, list_materials, preview_text, upload_material
from app.shared.models import Course, CourseMaterial, Lesson, User


class CourseMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (User.__table__, Course.__table__, Lesson.__table__, CourseMaterial.__table__):
            table.create(self.engine)
        with Session(self.engine) as db:
            db.add_all([User(id="u1", username="owner", password_hash="x"), User(id="u2", username="other", password_hash="x")])
            db.add_all([Course(id="c1", owner_id="u1", name="数据结构"), Course(id="c2", owner_id="u2", name="其他课程")])
            db.add_all([Lesson(id="l1", course_id="c1", title="第一讲"), Lesson(id="l2", course_id="c2", title="另一讲")])
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_upload_lists_only_own_course_and_valid_lesson(self):
        with Session(self.engine) as db, patch("app.modules.materials.service.upload_file") as storage:
            result = upload_material(db, "c1", "l1", UploadFile(filename="讲义.pdf", file=BytesIO(b"%PDF-example")), "owner")
            self.assertEqual(result.lesson_id, "l1")
            self.assertEqual(result.size_bytes, 12)
            self.assertTrue(result.object_key.startswith("materials/c1/"))
            storage.assert_called_once()
            self.assertEqual([item.id for item in list_materials(db, "c1", "owner")], [result.id])
            with self.assertRaises(HTTPException) as denied:
                list_materials(db, "c1", "other")
            self.assertEqual(denied.exception.status_code, 404)

    def test_rejects_foreign_lesson_and_unsupported_file(self):
        with Session(self.engine) as db, patch("app.modules.materials.service.upload_file") as storage:
            with self.assertRaises(HTTPException) as wrong_lesson:
                upload_material(db, "c1", "l2", UploadFile(filename="讲义.pdf", file=BytesIO(b"content")), "owner")
            self.assertEqual(wrong_lesson.exception.status_code, 400)
            with self.assertRaises(HTTPException) as wrong_type:
                upload_material(db, "c1", None, UploadFile(filename="script.exe", file=BytesIO(b"content")), "owner")
            self.assertEqual(wrong_type.exception.status_code, 400)
            self.assertEqual(db.scalar(select(CourseMaterial)), None)
            storage.assert_not_called()

    def test_download_checks_course_owner_before_reading_storage(self):
        with Session(self.engine) as db, patch("app.modules.materials.service.upload_file"):
            material = upload_material(db, "c1", None, UploadFile(filename="讲义.pdf", file=BytesIO(b"%PDF-example")), "owner")
            with patch("app.modules.materials.service.materialize_file") as storage:
                with self.assertRaises(HTTPException) as denied:
                    get_material_file(db, "c1", material.id, "other")
                self.assertEqual(denied.exception.status_code, 404)
                storage.assert_not_called()

    def test_docx_text_preview(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.docx"
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:p><w:r><w:t>第二段</w:t></w:r></w:p></w:body></w:document>')
            text, truncated = preview_text(path, "sample.docx")
            self.assertEqual(text, "第一段\n第二段")
            self.assertFalse(truncated)

    def test_office_preview_conversion_and_cleanup(self):
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "presentation.pptx"
            source.write_bytes(b"example")

            def write_pdf(command, **_kwargs):
                output = Path(command[command.index("--outdir") + 1]) / "presentation.pdf"
                output.write_bytes(b"%PDF-1.7")
                return SimpleNamespace(returncode=0)

            with patch("app.modules.materials.service.shutil.which", return_value="/usr/bin/soffice"), \
                 patch("app.modules.materials.service.subprocess.run", side_effect=write_pdf):
                converted, directory = convert_office_to_pdf(source, source.name)
            self.assertEqual(converted.read_bytes(), b"%PDF-1.7")
            cleanup_converted_preview(directory, None)
            self.assertFalse(directory.exists())


if __name__ == "__main__":
    unittest.main()

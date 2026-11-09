"""真实文件解析与数据库版本切换，网络边界使用模拟。"""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.materials.extraction import ExtractionError, extract_units
from app.modules.materials.processing import enqueue_material, process_material_content
from app.shared.models import Course, CourseMaterial, Lesson, MaterialChunk, MaterialProcessing, User, now_utc


@pytest.fixture
def material_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id="u", username="owner", password_hash="x"))
        db.add(Course(id="c", owner_id="u", name="数据结构"))
        db.add(Lesson(id="l", course_id="c", title="第一讲"))
        db.add(CourseMaterial(id="m", course_id="c", lesson_id="l", filename="讲义.txt", content_type="text/plain", object_key="materials/m.txt", size_bytes=20))
        db.commit()
        yield db
    engine.dispose()


def test_text_docx_pptx_positions(tmp_path):
    text = tmp_path / "test.txt"
    text.write_text("第一段\n\n第二段", encoding="utf-8")
    assert [item["locator_number"] for item in extract_units(text, text.name)] == [1, 2]
    doc = tmp_path / "test.docx"
    with ZipFile(doc, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>二叉树</w:t></w:r></w:p></w:document>')
    assert extract_units(doc, doc.name)[0]["content"] == "二叉树"
    ppt = tmp_path / "test.pptx"
    with ZipFile(ppt, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:r><a:t>二叉树</a:t></a:r></a:p>')
        archive.writestr("ppt/slides/slide2.xml", '<a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:r><a:t>叶子结点</a:t></a:r></a:p>')
    assert [(item["locator_number"], item["content"]) for item in extract_units(ppt, ppt.name)] == [(1, "二叉树"), (2, "叶子结点")]


def test_pdf_and_empty_pdf(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=400)
    writer.write(path)
    with pytest.raises(ExtractionError, match="OCR"):
        extract_units(path, path.name)
    writer = PdfWriter()
    writer.add_blank_page(width=400, height=400)
    writer.encrypt("password")
    writer.write(path)
    with pytest.raises(ExtractionError, match="加密"):
        extract_units(path, path.name)


def test_parse_retry_and_atomic_version(material_db, tmp_path):
    db = material_db
    path = tmp_path / "test.txt"
    path.write_text("二叉树的每个结点至多有两棵子树。", encoding="utf-8")
    with patch("app.modules.materials.processing.dispatch_one", return_value=False), \
         patch("app.modules.materials.processing.materialize_file", return_value=(path, False)), \
         patch("app.modules.materials.processing.embed_texts", side_effect=lambda texts: [[0.1] * 1536 for _ in texts]):
        state = enqueue_material(db, db.get(CourseMaterial, "m"))
        generation = state.generation
        assert state.status == "queued"
        assert process_material_content(db, "m", generation) == 1
        assert process_material_content(db, "m", generation) == 0
        db.expire_all()
        assert db.get(MaterialProcessing, "m").active_version == generation
        state = enqueue_material(db, db.get(CourseMaterial, "m"))
        retry_generation = state.generation
        with patch("app.modules.materials.processing.embed_texts", side_effect=RuntimeError("secret")):
            assert process_material_content(db, "m", retry_generation) == 0
        db.expire_all()
        state = db.get(MaterialProcessing, "m")
        assert state.status == "failed" and state.active_version == generation
        assert "secret" not in state.error_message
        assert db.scalar(select(MaterialChunk)).version == generation


def test_recycled_material_not_processed(material_db):
    db = material_db
    with patch("app.modules.materials.processing.dispatch_one"):
        state = enqueue_material(db, db.get(CourseMaterial, "m"))
        generation = state.generation
    db.get(CourseMaterial, "m").deleted_at = now_utc()
    db.commit()
    with patch("app.modules.materials.processing.materialize_file") as read:
        assert process_material_content(db, "m", generation) == 0
        read.assert_not_called()

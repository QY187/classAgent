"""预览使用实际保存数据与最终PDF生成器，覆盖范围与临时文件生命周期。"""
import json
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from test_course_export import export_db, pdf_text, read_archive
from test_course_export_contents import rich_export
from app.core.db import get_db
from app.core.deps import get_current_user
from app.modules.exports.controller import router, preview_course
from app.modules.exports.schemas import CourseExport, ExportContents
from app.modules.exports.service import build_course_archive


def preview(db, document=None, payload=None, user="owner", course="c"):
    return preview_course(course, payload or CourseExport(), document, user, db)


def test_manifest_and_single_pdf_share_saved_content_and_renderer(export_db):
    final = read_archive(export_db)
    with patch("app.modules.exports.service.render_pdf", wraps=__import__("app.modules.exports.service", fromlist=["render_pdf"]).render_pdf) as render:
        manifest = json.loads(preview(export_db).body)["documents"]
        assert render.call_count == 0  # 枚举不渲染全课程PDF
        assert manifest[0] == "课程目录.pdf" and set(manifest) == set(final)
        for name in manifest:
            response = preview(export_db, name)
            assert response.media_type == "application/pdf"
            assert response.headers["cache-control"] == "private, no-store"
            assert pdf_text(response.body) == pdf_text(final[name])
        assert render.call_count == len(manifest)  # 每次只渲染所选文档
    assert "我的修改" in pdf_text(preview(export_db, "002_同名课次/智能纪要.pdf").body)
    assert "暂无已保存的智能纪要" in pdf_text(preview(export_db, "001_同名课次/智能纪要.pdf").body)


def test_preview_enforces_owner_visible_scope_and_content_selection(export_db):
    for user, course, payload, status in [
        ("other", "c", CourseExport(), 404),
        ("owner", "foreign", CourseExport(), 404),
        ("owner", "c", CourseExport(lesson_ids=["deleted"]), 400),
        ("owner", "c", CourseExport(lesson_ids=["foreign"]), 400),
    ]:
        with pytest.raises(HTTPException) as error: preview(export_db, user=user, course=course, payload=payload)
        assert error.value.status_code == status
    payload = CourseExport(lesson_ids=["first"], contents=ExportContents(summaries=False, knowledge=False, quizzes=False))
    assert json.loads(preview(export_db, payload=payload).body)["documents"] == ["课程目录.pdf", "001_同名课次/文字记录.pdf"]
    for name in ["../secret", "002_同名课次/文字记录.pdf", "001_同名课次/智能纪要.pdf"]:
        with pytest.raises(HTTPException) as error: preview(export_db, name, payload)
        assert error.value.status_code == 404
    assert json.loads(preview(export_db, course="empty").body)["documents"] == ["课程目录.pdf"]


def test_preview_removes_temp_archive_on_success_unknown_document_and_failure(export_db, tmp_path):
    import tempfile
    def create(**kwargs): return tempfile.mkstemp(dir=tmp_path, **kwargs)
    with patch("app.modules.exports.service.mkstemp", side_effect=create):
        preview(export_db)
        assert not list(tmp_path.iterdir())
        preview(export_db, "课程目录.pdf")
        assert not list(tmp_path.iterdir())
        with pytest.raises(HTTPException): preview(export_db, "missing.pdf")
        assert not list(tmp_path.iterdir())
        with patch("app.modules.exports.service.render_pdf", side_effect=RuntimeError("render failed")):
            with pytest.raises(RuntimeError): preview(export_db, "课程目录.pdf")
        assert not list(tmp_path.iterdir())


def test_http_preview_requires_auth_and_returns_inline_pdf(export_db):
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as client:
        assert client.post("/courses/c/export/preview", json={}).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: "owner"
        path, filename = build_course_archive(export_db, "c", CourseExport(), "owner", preview_document="课程目录.pdf")
        with patch("app.modules.exports.controller.build_course_archive", return_value=(path, filename)):
            response = client.post("/courses/c/export/preview", params={"document": "课程目录.pdf"}, json={})
        assert response.status_code == 200 and response.headers["content-disposition"] == "inline"
        assert response.content.startswith(b"%PDF-") and not path.exists()


def test_shared_quiz_preview_obeys_selected_lessons_and_has_no_answers(rich_export):
    db, _ = rich_export
    name = "课程公共资料/小测题目.pdf"
    text = pdf_text(preview(db, name).body)
    assert "multi题目" in text and "course题目" in text
    assert "解析独有内容" not in text and "出题原文独有内容" not in text and "multi-hidden题目" not in text
    payload = CourseExport(lesson_ids=["first", "second"])
    assert "course题目" not in pdf_text(preview(db, name, payload).body)
    with pytest.raises(HTTPException) as error: preview(db, name, CourseExport(lesson_ids=["first"]))
    assert error.value.status_code == 404


def test_scope_change_during_build_does_not_release_preview(export_db):
    from app.modules.exports.service import selected_scope
    calls = 0
    def changed(*args):
        nonlocal calls
        calls += 1
        course, lessons = selected_scope(*args)
        return course, lessons if calls == 1 else []
    with patch("app.modules.exports.service.selected_scope", side_effect=changed):
        with pytest.raises(HTTPException) as error: preview(export_db, "002_同名课次/智能纪要.pdf")
        assert error.value.status_code == 409

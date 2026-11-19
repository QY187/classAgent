"""课程ZIP使用真实SQLite与实际归档，覆盖权限、范围、内容和文件生命周期。"""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile
import json

from pypdf import PdfReader

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base, get_db
from app.core.deps import get_current_user
from app.shared.models import Course, Lesson, LessonSummary, SpeakerAlias, TranscriptSegment, User, now_utc
from app.modules.exports.controller import router
from app.modules.exports.schemas import CourseExport
from app.modules.exports.service import build_course_archive, safe_name
from app.modules.exports.render import summary_markdown


@pytest.fixture
def export_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id="u", username="owner", password_hash="x"), User(id="other", username="other", password_hash="x")]); db.flush()
        db.add_all([Course(id="c", owner_id="u", name="数据/结构", semester="2026秋"), Course(id="empty", owner_id="u", name="空课程"), Course(id="foreign", owner_id="other", name="他人课程")]); db.flush()
        db.add_all([Lesson(id="first", course_id="c", title="同名课次", sort_order=1, lesson_date="2026-11-22"), Lesson(id="second", course_id="c", title="同名课次", sort_order=0), Lesson(id="deleted", course_id="c", title="回收站课次", deleted_at=now_utc()), Lesson(id="foreign", course_id="foreign", title="他人课次")]); db.flush()
        db.add_all([TranscriptSegment(id="s1", lesson_id="first", speaker="speaker_1", start_ms=3600000, end_ms=3605000, text="唯一的课堂原文。"), TranscriptSegment(id="hidden", lesson_id="deleted", start_ms=0, end_ms=1, text="已删除内容"), SpeakerAlias(lesson_id="first", raw_label="speaker_1", display_name="老师")])
        db.add(LessonSummary(lesson_id="first", status="edited", content='<h1>我的修改</h1><p>保留已保存内容。</p><ul><li><p>复习重点</p></li></ul><script>secretBad()</script><img src="https://external.test/track">'))
        db.commit()
        yield db
    engine.dispose()


def read_archive(db, payload=None, **kwargs):
    path, name = build_course_archive(db,"c",payload or CourseExport(),"owner",**kwargs)
    try:
        with ZipFile(path) as archive:
            assert archive.testzip() is None
            return {name: archive.read(name) for name in archive.namelist()}
    finally:
        path.unlink()


def pdf_text(data):
    assert data.startswith(b"%PDF-")
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_zip_uses_course_order_unique_safe_names_and_current_edits(export_db):
    files = read_archive(export_db)
    assert len(files) == 9 and all(name.endswith('.pdf') for name in files)
    assert list(files)[0] == '001_同名课次/智能纪要.pdf'
    summary = pdf_text(files['002_同名课次/智能纪要.pdf'])
    assert '我的修改' in summary and '复习重点' in summary
    assert 'secretBad' not in summary and 'external.test' not in summary
    text = pdf_text(files['002_同名课次/文字记录.pdf'])
    assert '01:00:00 - 01:00:05 | 老师' in text
    assert '已删除内容' not in ''.join(pdf_text(value) for value in files.values())
    assert all('..' not in name and not name.startswith('/') for name in files)


def test_selected_scope_excludes_unselected_and_rejects_foreign_or_deleted(export_db):
    files=read_archive(export_db,CourseExport(lesson_ids=['first']))
    assert len(files)==5 and '唯一的课堂原文' in pdf_text(files['001_同名课次/文字记录.pdf'])
    for ids in [['foreign'],['deleted'],['missing']]:
        with pytest.raises(HTTPException) as error:read_archive(export_db,CourseExport(lesson_ids=ids))
        assert error.value.status_code==400
    with pytest.raises(HTTPException) as error:build_course_archive(export_db,'c',CourseExport(),'other')
    assert error.value.status_code==404
    for ids in [[],[' ']]:
        with pytest.raises(ValidationError):CourseExport(lesson_ids=ids)
    assert CourseExport(lesson_ids=['first','first']).lesson_ids==['first']


def test_empty_course_and_missing_material_are_explicit(export_db):
    path,_=build_course_archive(export_db,'empty',CourseExport(),'owner')
    try:
        with ZipFile(path) as archive:
            assert archive.namelist()==['课程目录.pdf']
            assert '暂无可导出的课次' in pdf_text(archive.read('课程目录.pdf'))
    finally:path.unlink()
    files=read_archive(export_db,CourseExport(lesson_ids=['second']))
    assert '暂无已保存的智能纪要' in pdf_text(files['001_同名课次/智能纪要.pdf'])


def test_failed_build_removes_partial_archive(export_db,tmp_path):
    import tempfile
    def create(**kwargs):return tempfile.mkstemp(dir=tmp_path,**kwargs)
    with patch('app.modules.exports.service.mkstemp',side_effect=create), patch('app.modules.exports.service.MAX_BYTES',10):
        with pytest.raises(HTTPException)as error:read_archive(export_db)
        assert error.value.status_code==413
    assert not list(tmp_path.iterdir())


def test_response_stream_cleanup_even_when_send_fails(tmp_path):
    import asyncio
    from app.modules.exports.controller import ExportResponse
    path=tmp_path/'result.zip';path.write_bytes(b'example')
    async def fail(message):raise RuntimeError('connection lost')
    async def receive():return {'type':'http.disconnect'}
    with pytest.raises(RuntimeError):asyncio.run(ExportResponse(path)({'type':'http','method':'GET','headers':[],'extensions':{}},receive,fail))
    assert not path.exists()


def test_http_download_is_authenticated_and_removes_temp_file(tmp_path):
    app=FastAPI();app.include_router(router)
    path=tmp_path/'course.zip'
    with ZipFile(path,'w')as z:z.writestr('课程目录.md','目录')
    app.dependency_overrides[get_db]=lambda:None
    with TestClient(app)as client:
        assert client.post('/courses/c/export',json={}).status_code==401
        app.dependency_overrides[get_current_user]=lambda:'owner'
        with patch('app.modules.exports.controller.build_course_archive',return_value=(path,'数据结构.zip')):
            response=client.post('/courses/c/export',json={})
        assert response.status_code==200
        assert response.headers['content-type']=='application/zip'
        assert "filename*=utf-8''" in response.headers['content-disposition']
        assert response.headers['cache-control']=='private, no-store'
        assert not path.exists()
        with ZipFile(BytesIO(response.content))as archive:assert archive.read('课程目录.md').decode()=='目录'


def test_filename_and_structured_summary_keep_content_as_text():
    assert safe_name('../../CON')=='_.._CON'
    assert safe_name('CON.txt')=='_CON.txt'
    assert safe_name('...')=='未命名'
    data={'overview':'A < B','chapter_flow':[{'title':'第一章','summary':'正文'}],'topics':[{'title':'主题','points':['要点']}],'key_concepts':[{'term':'定义','definition':'内容'}],'examples':[{'title':'例题','explanation':'推导'}],'review_questions':['自测'],'to_verify':['待核对'],'keywords':['术语']}
    text=summary_markdown(json.dumps(data,ensure_ascii=False),'completed')
    for value in ['第一章','要点','内容','推导','自测','待核对','术语']:assert value in text
    assert r'A \< B' in text

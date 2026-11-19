from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zipfile import ZipFile
import json

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from sqlalchemy import select

from app.modules.exports.schemas import CourseExport, ExportContents
from app.modules.exports.service import Archive, build_course_archive
from app.shared.models import AudioFile, CourseMaterial, Quiz, QuizQuestion, ReviewCard
from test_course_export import export_db, pdf_text


@pytest.fixture
def rich_export(export_db,tmp_path,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),'storage_backend','local')
    monkeypatch.setattr(get_settings(),'local_storage_path',str(tmp_path/'storage'))
    root=tmp_path/'storage';root.mkdir()
    db=export_db
    db.add_all([ReviewCard(id='card-a',course_id='c',lesson_id='first',title='叶子节点',body='卡片独有内容',status='review',source_start_ms=1000,source_excerpt='卡片来源'),ReviewCard(id='card-b',course_id='c',lesson_id='second',title='未选卡片',body='不应导出B'),ReviewCard(id='card-hidden',course_id='c',lesson_id='deleted',title='回收站卡片',body='不应导出回收站')])
    records=[AudioFile(id='audio-a',lesson_id='first',filename='录音.mp3',object_key='audio-a',content_type='audio/mpeg',size_bytes=7),AudioFile(id='audio-a2',lesson_id='first',filename='录音.mp3',object_key='audio-a2',content_type='audio/mpeg',size_bytes=8),AudioFile(id='audio-b',lesson_id='second',filename='未选录音.mp3',object_key='audio-b',content_type='audio/mpeg',size_bytes=5)]
    for identity,lesson,title in [('public',None,'公共讲义.txt'),('material-a','first','讲义.txt'),('material-b','second','未选讲义.txt'),('hidden','deleted','回收站讲义.txt'),('foreign','foreign','他人讲义.txt')]:
        records.append(CourseMaterial(id=identity,course_id='foreign' if identity=='foreign' else 'c',lesson_id=lesson,filename=title,object_key=identity,content_type='text/plain',size_bytes=10))
    db.add_all(records)
    for record in records:(root/record.object_key).write_bytes(b'fixed-'+record.id.encode()+b'\x00\xff')
    for identity,ids,lesson in [('solo-a',['first'],'first'),('solo-b',['second'],'second'),('multi',['first','second'],None),('course',[],None),('deleted',['deleted'],'deleted'),('multi-hidden',['first','deleted'],None)]:
        quiz=Quiz(id=identity,course_id='c',lesson_id=lesson,lesson_ids_json=json.dumps(ids) if ids else None,title=identity+'小测',status='ready')
        quiz.questions=[QuizQuestion(position=1,kind='single_choice',stem=identity+'题目',options_json=json.dumps(['选项甲','乙','丙','丁'],ensure_ascii=False),correct_option=0,explanation='解析独有内容_'+identity,source_lesson_id=lesson,source_start_ms=0,source_excerpt='出题原文独有内容_'+identity)]
        db.add(quiz)
    db.commit()
    return db,root


def archive_bytes(db,contents,ids=None):
    path,_=build_course_archive(db,'c',CourseExport(lesson_ids=ids,contents=contents),'owner')
    try:
        with ZipFile(path)as archive:
            assert archive.testzip()is None
            return {name:archive.read(name)for name in archive.namelist()}
    finally:path.unlink()


def selection(**values):
    return ExportContents(**({key: False for key in ['summaries','knowledge','quizzes','transcripts']} | values))


def test_only_selected_contents_and_lesson_scope_are_archived(rich_export):
    db, _ = rich_export
    files = archive_bytes(db, selection(knowledge=True), ['first'])
    assert set(files) == {'001_同名课次/知识点.pdf', '课程目录.pdf'}
    text = pdf_text(files['001_同名课次/知识点.pdf'])
    assert '卡片独有内容' in text and '需要复习' in text and '卡片来源' in text
    assert '不应导出B' not in text


def test_question_only_pdf_and_scope(rich_export):
    db, _ = rich_export
    files = archive_bytes(db, selection(quizzes=True), ['first'])
    assert len(files) == 2
    text = pdf_text(files['001_同名课次/小测题目.pdf'])
    assert 'solo-a题目' in text and '选项甲' in text
    assert '解析独有内容' not in text and '出题原文独有内容' not in text
    assert 'solo-b题目' not in text and 'course题目' not in text
    both = archive_bytes(db, selection(quizzes=True), ['first','second'])
    shared = pdf_text(both['课程公共资料/小测题目.pdf'])
    assert 'multi题目' in shared and 'course题目' not in shared
    all_course = archive_bytes(db, selection(quizzes=True))
    combined = ''.join(pdf_text(data) for data in all_course.values())
    assert 'course题目' in combined and 'multi-hidden题目' not in combined and 'deleted题目' not in combined
    assert '解析独有内容' not in combined and '出题原文独有内容' not in combined


def test_defaults_four_pdfs_never_include_originals(rich_export):
    db, _ = rich_export
    files = archive_bytes(db, ExportContents())
    assert len(files) == 10 and all(name.endswith('.pdf') for name in files)
    assert all(set(name.rsplit('/',1)[-1] for name in files if name.startswith(folder)) == {'智能纪要.pdf','知识点.pdf','小测题目.pdf','文字记录.pdf'} for folder in ['001_', '002_'])
    assert set(ExportContents().model_dump().values()) == {True}


def test_invalid_content_combinations_are_rejected():
    for values in [dict(summaries=False,knowledge=False,quizzes=False,transcripts=False),dict(answers=True),dict(audio=False),dict(materials=False),dict(quizzes='true'),dict(unknown=True)]:
        with pytest.raises(ValidationError): ExportContents(**values)


def test_pdf_failure_removes_partial_zip(export_db,tmp_path):
    import tempfile
    with patch('app.modules.exports.service.mkstemp',side_effect=lambda **kwargs:tempfile.mkstemp(dir=tmp_path,**kwargs)), patch('app.modules.exports.service.render_pdf',side_effect=HTTPException(503,'PDF生成失败')), pytest.raises(HTTPException):
        build_course_archive(export_db,'c',CourseExport(),'owner')
    assert not list(tmp_path.iterdir())


def test_file_count_limit_removes_partial_zip(rich_export,tmp_path):
    import tempfile
    db,_=rich_export
    output=tmp_path/'output';output.mkdir()
    with patch('app.modules.exports.service.mkstemp',side_effect=lambda **kwargs:tempfile.mkstemp(dir=output,**kwargs)),patch('app.modules.exports.service.MAX_FILES',1),pytest.raises(HTTPException)as error:
        archive_bytes(db,selection(knowledge=True),['first'])
    assert error.value.status_code==413 and not list(output.iterdir())


def test_scope_changed_during_export_does_not_return_old_archive(export_db,tmp_path):
    import tempfile
    from app.shared.models import Lesson,now_utc
    from app.modules.exports.render import summary_markdown as original
    def mutate(content,status):
        rendered=original(content,status)
        export_db.get(Lesson,'first').deleted_at=now_utc();export_db.flush()
        return rendered
    with patch('app.modules.exports.service.mkstemp',side_effect=lambda **kwargs:tempfile.mkstemp(dir=tmp_path,**kwargs)),patch('app.modules.exports.service.summary_markdown',side_effect=mutate),pytest.raises(HTTPException):
        build_course_archive(export_db,'c',CourseExport(lesson_ids=['first']),'owner')
    assert not list(tmp_path.iterdir())


def test_long_pdf_has_embedded_chinese_font_page_numbers_and_limit():
    from io import BytesIO
    from pypdf import PdfReader
    from app.modules.exports.pdf import render_pdf
    content = '# 分页校验\n\n' + '\n\n'.join(f'## 第{i}段\n\n' + '中文正文与数学概念，保持完整可阅读。'*15 for i in range(30))
    data = render_pdf(content)
    reader = PdfReader(BytesIO(data))
    assert len(reader.pages) > 2
    for index, page in enumerate(reader.pages, 1):
        assert f'{index} / {len(reader.pages)}' in page.extract_text()
    fonts = reader.pages[0]['/Resources']['/Font'].get_object().values()
    assert any('/FontFile2' in ref.get_object().get('/FontDescriptor', {}).get_object() for ref in fonts if ref.get_object().get('/FontDescriptor'))
    with patch('app.modules.exports.pdf.MAX_PAGES',1), pytest.raises(HTTPException) as error:
        render_pdf(content)
    assert error.value.status_code == 413

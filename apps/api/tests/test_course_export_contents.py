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
from app.modules.exports.extras import add_binary
from app.shared.models import AudioFile, CourseMaterial, Quiz, QuizQuestion, ReviewCard
from test_course_export import export_db


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
    return ExportContents(summaries=False,transcripts=False,**values)


def test_only_selected_contents_and_lesson_scope_are_archived(rich_export):
    db,root=rich_export
    files=archive_bytes(db,selection(knowledge=True),['first'])
    assert set(files)=={'001_同名课次/知识点.md','课程目录.md'}
    text=files['001_同名课次/知识点.md'].decode()
    assert '卡片独有内容'in text and '需要复习'in text and '卡片来源'in text
    assert '不应导出B'not in text
    assert not any(name.endswith(('.mp3','.txt'))for name in files)


def test_practice_and_answer_exports_are_separate_and_quizzes_obey_scope(rich_export):
    db,_=rich_export
    practice=archive_bytes(db,selection(quizzes=True),['first'])
    quiz_files=[(name,data.decode())for name,data in practice.items()if '小测/'in name]
    assert len(quiz_files)==1 and 'solo-a'in quiz_files[0][0]
    text=quiz_files[0][1]
    assert '选项甲'in text and '解析独有内容'not in text and '出题原文独有内容'not in text and '**正确答案**'not in text
    answered=archive_bytes(db,selection(quizzes=True,answers=True),['first'])
    answer=next(data.decode()for name,data in answered.items()if '小测/'in name)
    assert '**正确答案**：A. 选项甲'in answer and '解析独有内容' in answer
    assert '出题原文独有内容' in answer
    both=archive_bytes(db,selection(quizzes=True),['first','second'])
    assert any('multi小测'in name for name in both)
    assert not any('course小测' in name or 'multi-hidden' in name or 'deleted小测' in name for name in both)
    all_course=archive_bytes(db,selection(quizzes=True))
    assert any('course小测'in name for name in all_course)
    assert not any('multi-hidden'in name or 'deleted小测'in name for name in all_course)


def test_binary_files_keep_bytes_names_and_include_public_materials(rich_export):
    db,root=rich_export
    files=archive_bytes(db,selection(audio=True,materials=True),['first'])
    binary={name:data for name,data in files.items()if name.endswith(('.mp3','.txt'))}
    assert len(binary)==4
    assert set(binary.values())=={(root/key).read_bytes()for key in ['audio-a','audio-a2','public','material-a']}
    assert sum(name.endswith('_录音.mp3')for name in binary)==2
    assert any(name.startswith('课程公共资料/')for name in binary)
    assert not any('未选'in name or '回收站'in name or '他人'in name for name in files)
    db.get(CourseMaterial,'material-a').filename='很长的文件名'*40+'.txt';db.commit()
    files=archive_bytes(db,selection(materials=True),['first'])
    assert all(Path(name).suffix=='.txt'for name in files if '/上传课件/'in name)
    assert all(len(Path(name).name)<=84 for name in files)


def test_missing_originals_are_listed_without_server_paths(rich_export):
    db,root=rich_export
    (root/'material-a').unlink()
    files=archive_bytes(db,selection(materials=True),['first'])
    index=files['课程目录.md'].decode()
    assert '原文件缺失提醒'in index and '讲义'in index and '原文件不存在'in index
    assert str(root)not in index and 'object_key'not in index
    assert not any(name.endswith('_讲义.txt')and not name.startswith('课程公共资料')for name in files)


def test_empty_and_invalid_content_combinations_are_rejected():
    for values in [dict(summaries=False,transcripts=False),dict(summaries=False,transcripts=False,answers=True),dict(quizzes=False,answers=True),dict(audio='true'),dict(unknown=True)]:
        with pytest.raises(ValidationError):ExportContents(**values)
    assert ExportContents().summaries and ExportContents().transcripts
    assert not ExportContents().audio and not ExportContents().answers


def test_oversized_originals_fail_before_reading_and_cleanup(rich_export,tmp_path):
    db,_=rich_export
    db.get(AudioFile,'audio-a').size_bytes=513*1024*1024;db.commit()
    import tempfile
    output=tmp_path/'temp';output.mkdir()
    with patch('app.modules.exports.service.mkstemp',side_effect=lambda **kwargs:tempfile.mkstemp(dir=output,**kwargs)),patch('app.modules.exports.extras.add_binary')as read:
        with pytest.raises(HTTPException)as error:archive_bytes(db,selection(audio=True),['first'])
    assert error.value.status_code==413 and not list(output.iterdir())
    read.assert_not_called()


def test_s3_stream_closes_resources_on_success_and_failure(tmp_path):
    archive=Archive(tmp_path/'test.zip')
    record=SimpleNamespace(object_key='key',size_bytes=4)
    settings=SimpleNamespace(storage_backend='s3',s3_bucket='bucket')
    response=Mock();response.stream.return_value=iter([b'ab',b'cd'])
    with patch('app.modules.exports.extras.get_settings',return_value=settings),patch('app.modules.exports.extras.get_client',return_value=SimpleNamespace(get_object=lambda *_:response)):
        assert add_binary(archive,record,'音频.mp3')
    response.close.assert_called_once();response.release_conn.assert_called_once();archive.close()
    with ZipFile(tmp_path/'test.zip')as z:assert z.read('音频.mp3')==b'abcd'
    archive=Archive(tmp_path/'failed.zip');response=Mock()
    def broken(*args):yield b'part';raise OSError('private server address')
    response.stream.side_effect=broken
    with patch('app.modules.exports.extras.get_settings',return_value=settings),patch('app.modules.exports.extras.get_client',return_value=SimpleNamespace(get_object=lambda *_:response)),pytest.raises(HTTPException)as error:
        add_binary(archive,record,'音频.mp3')
    assert 'private server'not in error.value.detail
    response.close.assert_called_once();response.release_conn.assert_called_once();archive.close()


def test_binary_path_escape_is_rejected_and_archive_removed(rich_export,tmp_path):
    db,_=rich_export
    db.get(AudioFile,'audio-a').object_key='../outside';db.commit()
    with pytest.raises(HTTPException)as error:archive_bytes(db,selection(audio=True),['first'])
    assert error.value.status_code==503


def test_material_quiz_answers_keep_position_and_stale_source_warning(rich_export):
    from app.shared.models import MaterialChunk, MaterialProcessing
    db,_=rich_export
    material=db.get(CourseMaterial,'material-a')
    db.add(MaterialProcessing(material_id=material.id,status='ready',active_version='v1'))
    db.add(MaterialChunk(id='chunk',material_id=material.id,version='v1',position=0,locator_type='page',locator_number=3,content='可核对的课件引用内容',embedding=[0.0]*1536))
    question=db.scalar(select(QuizQuestion).where(QuizQuestion.quiz_id=='solo-a'))
    question.source_material_json=json.dumps({'source_type':'material','course_id':'c','material_id':material.id,'chunk_id':'chunk','version':'v1','filename':material.filename,'locator_label':'第3页','snippet':'课件引用内容'})
    question.source_excerpt='课件引用内容';db.commit()
    files=archive_bytes(db,selection(quizzes=True,answers=True),['first'])
    answer=next(value.decode()for name,value in files.items()if '/小测/'in name)
    assert '第3页'in answer and '当前可核对'in answer and '课件引用内容'in answer
    db.get(MaterialProcessing,material.id).active_version='v2';db.commit()
    files=archive_bytes(db,selection(quizzes=True,answers=True),['first'])
    assert '原文件已变更或不可用'in next(value.decode()for name,value in files.items()if '/小测/'in name)


def test_public_files_export_even_when_course_has_no_lessons(rich_export):
    db,root=rich_export
    (root/'empty-file').write_bytes(b'original')
    db.add(CourseMaterial(id='empty-file',course_id='empty',filename='课程说明.txt',content_type='text/plain',object_key='empty-file',size_bytes=8));db.commit()
    path,_=build_course_archive(db,'empty',CourseExport(contents=selection(materials=True)),'owner')
    try:
        with ZipFile(path)as archive:
            assert archive.read('课程公共资料/上传课件/001_课程说明.txt')==b'original'
            assert len(archive.namelist())==2
    finally:path.unlink()


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

import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...shared.models import AudioFile, Lesson, LessonSummary, ProcessingJob, TranscriptSegment
from ...infrastructure.storage import upload_file
from . import mapper


def get_lesson(db: Session, lesson_id: str) -> Lesson:
    lesson = mapper.find_lesson(db, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    return lesson


def upload_audio(db: Session, lesson_id: str, file: UploadFile, browser_transcript: str | None) -> ProcessingJob:
    lesson = get_lesson(db, lesson_id)
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="请上传音频文件")

    object_key = f"lessons/{lesson_id}/{uuid4()}-{Path(file.filename or 'audio').name}"
    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    upload_file(object_key, file.file, size_bytes, file.content_type)
    audio = AudioFile(lesson_id=lesson_id, filename=file.filename or "audio", content_type=file.content_type, object_key=object_key, size_bytes=size_bytes)
    mapper.clear_transcript(db, lesson_id)
    db.execute(delete(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    chunks = _parse_browser_transcript(browser_transcript)
    for chunk in chunks:
        db.add(TranscriptSegment(lesson_id=lesson_id, speaker="说话人 1", start_ms=chunk["start_ms"], end_ms=chunk["end_ms"], text=chunk["text"], source="browser"))
    lesson.status = "completed" if chunks else "audio_only"
    if chunks:
        from ...core.config import get_settings

        db.add(LessonSummary(lesson_id=lesson_id, provider=get_settings().summary_provider, status="queued"))
    job = mapper.save_audio_job(db, audio, ProcessingJob(lesson_id=lesson_id, stage="completed", progress=100), lesson)
    if chunks:
        from ...infrastructure.tasks import generate_summary

        generate_summary.delay(lesson_id)
    return job


def latest_job(db: Session, lesson_id: str) -> ProcessingJob:
    job = mapper.find_latest_job(db, lesson_id)
    if job is None:
        raise HTTPException(status_code=404, detail="该课次暂无处理任务")
    return job


def get_transcript(db: Session, lesson_id: str) -> list[TranscriptSegment]:
    return mapper.find_transcript(db, lesson_id)


def _parse_browser_transcript(value: str | None) -> list[dict[str, int | str]]:
    if not value or not value.strip():
        return []
    try:
        chunks = json.loads(value)
    except json.JSONDecodeError:
        chunks = [{"text": value.strip(), "start_ms": 0, "end_ms": 0}]
    if not isinstance(chunks, list):
        chunks = [{"text": value.strip(), "start_ms": 0, "end_ms": 0}]
    parsed: list[dict[str, int | str]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict) or not str(chunk.get("text", "")).strip():
            continue
        start_ms = max(0, int(chunk.get("start_ms", 0) or 0))
        end_ms = max(start_ms, int(chunk.get("end_ms", start_ms) or start_ms))
        parsed.append({"start_ms": start_ms, "end_ms": end_ms, "text": str(chunk["text"]).strip()})
    return parsed

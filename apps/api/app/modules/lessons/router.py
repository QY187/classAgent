import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import AudioFile, Lesson, ProcessingJob, TranscriptSegment
from ...schemas import JobRead, LessonRead, TranscriptSegmentRead
from ...storage import upload_file
from ...tasks import process_audio


router = APIRouter(tags=["lessons"])


@router.get("/lessons/{lesson_id}", response_model=LessonRead)
def get_lesson(lesson_id: str, db: Session = Depends(get_db)) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    return lesson


@router.post("/lessons/{lesson_id}/audio", response_model=JobRead, status_code=202)
def upload_audio(lesson_id: str, file: UploadFile = File(...), browser_transcript: str | None = Form(None), db: Session = Depends(get_db)) -> ProcessingJob:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="请上传音频文件")

    object_key = f"lessons/{lesson_id}/{uuid4()}-{Path(file.filename or 'audio').name}"
    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    upload_file(object_key, file.file, size_bytes, file.content_type)
    audio = AudioFile(
        lesson_id=lesson_id,
        filename=file.filename or "audio",
        content_type=file.content_type,
        object_key=object_key,
        size_bytes=size_bytes,
    )
    db.execute(delete(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id))
    for chunk in _parse_browser_transcript(browser_transcript):
        db.add(TranscriptSegment(
            lesson_id=lesson_id,
            speaker="说话人 1",
            start_ms=chunk["start_ms"],
            end_ms=chunk["end_ms"],
            text=chunk["text"],
            source="browser",
        ))
    job = ProcessingJob(lesson_id=lesson_id, stage="queued", progress=0)
    lesson.status = "queued"
    db.add_all([audio, job])
    db.commit()
    db.refresh(job)
    process_audio.delay(job.id)
    return job


@router.get("/lessons/{lesson_id}/jobs/latest", response_model=JobRead)
def latest_job(lesson_id: str, db: Session = Depends(get_db)) -> ProcessingJob:
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.lesson_id == lesson_id).order_by(ProcessingJob.created_at.desc()))
    if job is None:
        raise HTTPException(status_code=404, detail="该课次暂无处理任务")
    return job


@router.get("/lessons/{lesson_id}/transcript", response_model=list[TranscriptSegmentRead])
def get_transcript(lesson_id: str, db: Session = Depends(get_db)) -> list[TranscriptSegment]:
    return list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms)))


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

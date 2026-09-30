import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...shared.models import AudioFile, Lesson, LessonSummary, ProcessingJob, SpeakerAlias, TranscriptRevision, TranscriptSegment
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
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".aac", ".amr", ".flac", ".m4a", ".mp3", ".mpeg", ".ogg", ".opus", ".wav", ".webm", ".wma"}:
        raise HTTPException(status_code=400, detail="不支持该音频格式，请上传 MP3、WAV、M4A、WebM 等常见格式")

    chunks = _parse_browser_transcript(browser_transcript)
    if not chunks:
        from ...core.config import get_settings

        if not get_settings().dashscope_api_key:
            raise HTTPException(status_code=503, detail="未配置 DASHSCOPE_API_KEY，无法转写上传的音频")

    object_key = f"lessons/{lesson_id}/{uuid4()}{suffix}"
    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    upload_file(object_key, file.file, size_bytes, file.content_type)
    audio = AudioFile(lesson_id=lesson_id, filename=file.filename or "audio", content_type=file.content_type, object_key=object_key, size_bytes=size_bytes)
    mapper.clear_transcript(db, lesson_id)
    db.execute(delete(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    for chunk in chunks:
        db.add(TranscriptSegment(lesson_id=lesson_id, speaker="说话人 1", start_ms=chunk["start_ms"], end_ms=chunk["end_ms"], text=chunk["text"], source="browser"))
    lesson.status = "completed" if chunks else "queued"
    if chunks:
        from ...core.config import get_settings

        db.add(LessonSummary(lesson_id=lesson_id, provider=get_settings().summary_provider, status="queued"))
    job = mapper.save_audio_job(
        db, audio,
        ProcessingJob(lesson_id=lesson_id, stage="completed" if chunks else "queued", progress=100 if chunks else 0),
        lesson,
    )
    if chunks:
        from ...infrastructure.tasks import generate_summary

        generate_summary.delay(lesson_id)
    else:
        from ...infrastructure.tasks import process_audio

        process_audio.delay(job.id, object_key)
    return job


def latest_job(db: Session, lesson_id: str) -> ProcessingJob:
    job = mapper.find_latest_job(db, lesson_id)
    if job is None:
        raise HTTPException(status_code=404, detail="该课次暂无处理任务")
    return job


def get_transcript(db: Session, lesson_id: str) -> list[TranscriptSegment]:
    return mapper.find_transcript(db, lesson_id)


def get_speakers(db: Session, lesson_id: str) -> list[dict[str, str]]:
    get_lesson(db, lesson_id)
    aliases = mapper.find_speaker_aliases(db, lesson_id)
    alias_map = {alias.raw_label: alias.display_name for alias in aliases}
    raw_labels = db.scalars(
        select(TranscriptSegment.speaker).where(TranscriptSegment.lesson_id == lesson_id).distinct()
    ).all()
    return [{"raw_label": label, "display_name": alias_map.get(label, label)} for label in raw_labels]


def save_speakers(db: Session, lesson_id: str, aliases: dict[str, str]) -> list[dict[str, str]]:
    get_lesson(db, lesson_id)
    cleaned = {raw: name.strip() or raw for raw, name in aliases.items() if raw}
    mapper.replace_speaker_aliases(db, lesson_id, cleaned)
    return get_speakers(db, lesson_id)


def merge_segments(db: Session, lesson_id: str, first_id: str, second_id: str) -> TranscriptSegment:
    get_lesson(db, lesson_id)
    try:
        return mapper.merge_transcript_segments(db, lesson_id, first_id, second_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def update_transcript_segment(db: Session, lesson_id: str, segment_id: str, text: str) -> TranscriptSegment:
    get_lesson(db, lesson_id)
    segment = db.get(TranscriptSegment, segment_id)
    if segment is None or segment.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="文字片段不存在")

    corrected = text.strip()
    if not corrected:
        raise HTTPException(status_code=400, detail="文字记录不能为空")
    if corrected == segment.text:
        return segment

    db.add(TranscriptRevision(
        segment_id=segment.id,
        previous_text=segment.text,
        updated_text=corrected,
        previous_source=segment.source,
    ))
    segment.text = corrected
    segment.source = "manual"
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    if summary is not None:
        summary.status = "stale"
        summary.content = None
        summary.error_message = None
    db.commit()
    db.refresh(segment)
    return segment


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

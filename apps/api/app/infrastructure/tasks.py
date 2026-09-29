from celery import Celery
from sqlalchemy import select
from pathlib import Path

from ..core.config import get_settings
from .asr import transcribe_file
from .storage import materialize_file
from ..modules.summaries.service import generate_summary as build_summary


celery_app = Celery("classagent", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.update(task_track_started=True, result_expires=3600)


@celery_app.task(name="classagent.process_audio")
def process_audio(job_id: str, object_key: str) -> None:
    from ..core.db import SessionLocal
    from ..shared.models import Lesson, LessonSummary, ProcessingJob, TranscriptSegment

    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            return
        lesson = db.get(Lesson, job.lesson_id)
        if lesson is None:
            raise RuntimeError("找不到对应课次")
        job.stage = "transcribing"
        job.progress = 30
        lesson.status = "transcribing"
        db.commit()

        audio_path, should_remove = materialize_file(object_key)
        try:
            segments = transcribe_file(Path(audio_path))
        finally:
            if should_remove:
                Path(audio_path).unlink(missing_ok=True)

        db.add_all([
            TranscriptSegment(
                lesson_id=lesson.id,
                speaker=segment.speaker,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
                source="paraformer",
            )
            for segment in segments
        ])
        if db.scalar(select(LessonSummary.id).where(LessonSummary.lesson_id == lesson.id)) is None:
            db.add(LessonSummary(lesson_id=lesson.id, provider=get_settings().summary_provider, status="queued"))
        job.stage = "completed"
        job.progress = 100
        lesson.status = "completed"
        db.commit()
        generate_summary.delay(lesson.id)
    except Exception as exc:
        db.rollback()
        job = db.get(ProcessingJob, job_id)
        if job is not None:
            job.stage = "failed"
            job.error_message = str(exc)
            lesson = db.get(Lesson, job.lesson_id)
            if lesson is not None:
                lesson.status = "failed"
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="classagent.generate_summary")
def generate_summary(lesson_id: str) -> None:
    from ..core.db import SessionLocal
    from ..shared.models import Lesson, LessonSummary, TranscriptSegment

    db = SessionLocal()
    summary = None
    try:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return
        summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
        if summary is None:
            summary = LessonSummary(lesson_id=lesson_id, provider=get_settings().summary_provider)
            db.add(summary)
        summary.status = "generating"
        summary.error_message = None
        summary.provider = get_settings().summary_provider
        db.commit()

        transcript_segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms)))
        payload = [
            {
                "index": index,
                "start": _format_time(segment.start_ms),
                "end": _format_time(segment.end_ms),
                "speaker": segment.speaker,
                "text": segment.text,
            }
            for index, segment in enumerate(transcript_segments, start=1)
        ]
        summary.content = build_summary(payload)
        summary.status = "completed"
        db.commit()
    except Exception as exc:
        db.rollback()
        if summary is None:
            summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
        if summary is not None:
            summary.status = "failed"
            summary.error_message = str(exc)
            db.commit()
        raise
    finally:
        db.close()


def _format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"

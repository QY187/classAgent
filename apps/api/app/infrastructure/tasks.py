from celery import Celery
from sqlalchemy import select

from ..core.config import get_settings
from ..modules.summaries.service import generate_summary as build_summary


celery_app = Celery("classagent", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.update(task_track_started=True, result_expires=3600)


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

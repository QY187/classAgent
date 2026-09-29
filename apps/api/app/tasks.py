from celery import Celery
from sqlalchemy import select

from .config import get_settings
from .summary import generate_summary as build_summary


celery_app = Celery("classagent", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.update(task_track_started=True, result_expires=3600)


@celery_app.task(name="classagent.process_audio")
def process_audio(job_id: str) -> None:
    from .db import SessionLocal
    from .models import Lesson, ProcessingJob, TranscriptSegment

    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            return
        lesson = db.get(Lesson, job.lesson_id)
        if lesson is None:
            job.stage = "failed"
            job.error_message = "找不到对应课次"
            db.commit()
            return

        job.stage = "transcribing"
        job.progress = 30
        lesson.status = "transcribing"
        db.commit()

        if get_settings().transcription_provider != "mock":
            raise RuntimeError("尚未配置真实语音识别服务，请将 TRANSCRIPTION_PROVIDER 设置为 mock 以运行技术验证版")

        has_transcript = db.scalar(select(TranscriptSegment.id).where(TranscriptSegment.lesson_id == lesson.id).limit(1))
        if has_transcript is None:
            db.add(TranscriptSegment(
                lesson_id=lesson.id,
                speaker="说话人 1",
                start_ms=0,
                end_ms=1000,
                text="这是技术验证版的模拟转写结果。接入真实 ASR 服务后，这里会替换为课堂原文。",
                source="mock",
            ))
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
    from .db import SessionLocal
    from .models import Lesson, LessonSummary, TranscriptSegment

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

from celery import Celery

from .config import get_settings


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


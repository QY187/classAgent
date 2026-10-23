"""失败转写重试；锁定课次，保留音频，已有文字不覆盖。"""
import json
from fastapi import HTTPException
from sqlalchemy import select
from ...shared.models import AgentAction, AudioFile, Lesson, ProcessingJob, TranscriptSegment
from .service import get_lesson
from .mapper import find_latest_job


def prepare_retry(db, lesson_id, username):
    get_lesson(db, lesson_id, username)
    lesson = db.scalar(select(Lesson).where(Lesson.id == lesson_id).with_for_update())
    job = find_latest_job(db, lesson_id)
    if lesson.status != "failed" or job is None or job.stage != "failed":
        raise HTTPException(409, "只可重试当前转写失败的课次；排队、处理中或已完成不会重复提交")
    if db.scalar(select(TranscriptSegment.id).where(TranscriptSegment.lesson_id == lesson_id).limit(1)):
        raise HTTPException(409, "已有课堂文字，不覆盖原文；请查看纪要或当前任务的失败原因")
    audio = db.scalar(select(AudioFile).where(AudioFile.lesson_id == lesson_id)
                      .order_by(AudioFile.created_at.desc(), AudioFile.id.desc()).limit(1))
    if audio is None:
        raise HTTPException(409, "没有可复用的录音，请先上传音频")
    from ...core.config import get_settings
    if not get_settings().dashscope_api_key:
        raise HTTPException(503, "未配置转写服务，无法重试")
    queued = ProcessingJob(lesson_id=lesson_id, stage="queued", progress=0)
    db.add(queued)
    lesson.status = "queued"
    db.flush()
    return {"kind":"action", "operation":"retry_transcription", "target":"lesson", "id":lesson.id,
            "course_id":lesson.course_id, "title":lesson.title, "job_id":queued.id, "audio_id":audio.id,
            "message":f"已登记课次“{lesson.title}”的转写重试，等待处理。"}


def dispatch_retry(db, result):
    # 回执和任务已经提交。重复投递由 worker 的任务阶段锁阻止重复转写。
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == result["job_id"]))
    audio = db.scalar(select(AudioFile).where(AudioFile.id == result["audio_id"]))
    if not job or job.stage != "queued" or not audio or audio.lesson_id != job.lesson_id:
        return False
    latest = find_latest_job(db, job.lesson_id)
    if not latest or latest.id != job.id:
        return False
    from ...infrastructure.tasks import process_audio
    process_audio.apply_async(args=(job.id, audio.object_key), task_id=job.id)
    return True


def dispatch_pending_retries(db):
    # AgentAction 是已提交的持久回执；队列短暂不可用时由 beat 补投递。
    receipts = db.scalars(select(AgentAction).where(AgentAction.tool == "retry_transcription")
                         .order_by(AgentAction.created_at.asc()).execution_options(yield_per=100))
    sent = 0
    for receipt in receipts:
        try:
            sent += bool(dispatch_retry(db, json.loads(receipt.result_json)))
            if sent >= 50:
                break
        except Exception:
            continue
    return sent

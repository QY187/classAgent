"""课次处理只读明细；音频存储路径和供应商凭据不进入结果。"""
from sqlalchemy import select
from ...shared.models import LessonSummary
from .service import get_lesson
from .mapper import find_latest_job
from ..courses.pending import processing_state


def get_processing_detail(db, lesson_id, username):
    lesson = get_lesson(db, lesson_id, username)
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    job = find_latest_job(db, lesson_id)
    state, label, error = processing_state(lesson, summary, job)
    if lesson.status == "completed" and summary and summary.status in {"completed", "edited"} and (summary.content or "").strip():
        state, label, error = "completed", "转写与纪要已完成", None
    current_failed = lesson.status == "failed" and job and job.stage == "failed"
    return {"lesson_id":lesson.id, "title":lesson.title, "course_id":lesson.course_id,
        "course_name":lesson.course.name, "lesson_status":lesson.status, "state":state,
        "stage_label":label, "error_message":error[:1000] if error else None,
        "transcription_job": {"id":job.id, "stage":job.stage, "progress":job.progress,
            "error_message":job.error_message[:1000] if current_failed and job.error_message else None,
            "created_at":job.created_at.isoformat()} if job else None,
        "summary_status":summary.status if summary else "missing",
        "summary_available":bool(summary and summary.status in {"completed", "edited"} and (summary.content or "").strip()), "href":f"/lessons/{lesson.id}"}

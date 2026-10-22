"""待处理课次明细，与首页统计共用筛选口径。"""
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...shared.models import Course, Lesson, LessonSummary, ProcessingJob


def pending_condition():
    ready = exists(select(LessonSummary.id).where(
        LessonSummary.lesson_id == Lesson.id,
        LessonSummary.status.in_(("completed", "edited")),
        LessonSummary.content.is_not(None), func.trim(LessonSummary.content) != "",
    ).correlate(Lesson))
    return (Lesson.status != "completed") | ~ready


def processing_state(lesson, summary, job):
    if lesson.status != "completed":
        if lesson.status == "queued":
            return "queued", "等待转写", None
        if lesson.status == "transcribing":
            return "transcribing", "正在转写", None
        if lesson.status == "failed":
            return "failed", "转写失败", (job.error_message if job and job.stage == "failed" else None) or "未记录具体原因，请进入课次查看处理任务。"
        if lesson.status == "created":
            return "created", "等待录音或上传", None
        return "incomplete", "转写尚未完成", None
    if summary:
        if summary.status == "failed":
            return "failed", "纪要生成失败", summary.error_message or "未记录具体原因，请进入课次查看纪要。"
        if summary.status == "queued":
            return "queued", "等待生成纪要", None
        if summary.status == "generating":
            return "generating", "正在生成纪要", None
        if summary.status == "stale":
            return "stale", "纪要需要更新", None
    return "missing_summary", "尚无可用纪要", None


def list_pending_lessons(db: Session, username: str, offset: int = 0, limit: int = 20, *, course_id: str | None = None, lesson_id: str | None = None):
    owner = user_id_for_username(db, username)
    conditions = [Course.owner_id == owner, pending_condition()]
    if course_id:
        conditions.append(Lesson.course_id == course_id)
    if lesson_id:
        conditions.append(Lesson.id == lesson_id)
    total = db.scalar(select(func.count(Lesson.id)).join(Course).where(*conditions)) or 0
    latest_job = select(ProcessingJob.id).where(ProcessingJob.lesson_id == Lesson.id).order_by(
        ProcessingJob.created_at.desc(), ProcessingJob.id.desc()).limit(1).correlate(Lesson).scalar_subquery()
    rows = db.execute(select(Lesson, Course, LessonSummary, ProcessingJob).join(Course)
        .outerjoin(LessonSummary, LessonSummary.lesson_id == Lesson.id)
        .outerjoin(ProcessingJob, ProcessingJob.id == latest_job)
        .where(*conditions).order_by(Lesson.created_at.desc(), Lesson.id.desc()).offset(offset).limit(limit)).all()
    items = []
    for lesson, course, summary, job in rows:
        state, label, error = processing_state(lesson, summary, job)
        items.append({"id": lesson.id, "title": lesson.title, "course_id": course.id,
                      "course_name": course.name, "lesson_date": lesson.lesson_date,
                      "state": state, "stage_label": label, "error_message": error[:1000] if error else None,
                      "href": f"/lessons/{lesson.id}"})
    return {"total": total, "items": items, "offset": offset, "limit": limit, "has_more": offset + len(items) < total}

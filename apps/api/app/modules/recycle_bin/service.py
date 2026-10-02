from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import Lesson, LessonSummary, now_utc
from .mapper import owned_item


def ensure_idle(db: Session, lesson_ids: list[str]):
    if not lesson_ids:
        return
    options = {"include_deleted": True}
    processing = db.scalar(select(Lesson.id).where(Lesson.id.in_(lesson_ids), Lesson.status.in_(("queued", "transcribing")))
                           .execution_options(**options).limit(1))
    summary = db.scalar(select(LessonSummary.id).where(LessonSummary.lesson_id.in_(lesson_ids), LessonSummary.status.in_(("queued", "generating")))
                        .execution_options(**options).limit(1))
    if processing or summary:
        raise HTTPException(status_code=409, detail="有课次正在排队、转写或生成纪要，请处理完成后再删除")


def move_to_bin(db: Session, kind: str, identity: str, username: str):
    item, course, lesson = owned_item(db, kind, identity, username)
    if item.deleted_at is not None or (kind != "course" and course.deleted_at is not None) or (lesson and lesson.deleted_at is not None):
        raise HTTPException(status_code=404, detail="内容不存在或已在回收站")
    if kind == "course":
        ids = list(db.scalars(select(Lesson.id).where(Lesson.course_id == identity).execution_options(include_deleted=True)))
        ensure_idle(db, ids)
    elif kind == "lesson":
        ensure_idle(db, [identity])
    item.deleted_at = now_utc()
    db.commit()
    db.expunge_all()

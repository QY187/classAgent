from fastapi import HTTPException
from sqlalchemy.orm import Session
from .mapper import owned_item
from .retention import is_expired
from ...shared.models import now_utc


def restore_item(db: Session, kind: str, identity: str, username: str) -> dict:
    item, course, lesson = owned_item(db, kind, identity, username)
    if item.deleted_at is None:
        raise HTTPException(status_code=409, detail="该项目已恢复或不在回收站")
    if is_expired(item.deleted_at, now_utc()):
        raise HTTPException(status_code=409, detail="已超过 30 天保留期，无法恢复，等待自动清理")
    if kind != "course" and course.deleted_at is not None:
        raise HTTPException(status_code=409, detail="请先恢复所属课程")
    if lesson and lesson.deleted_at is not None:
        raise HTTPException(status_code=409, detail="请先恢复所属课次")
    course_id = course.id
    item.deleted_at = None
    db.commit()
    db.expunge_all()
    return {"id": identity, "kind": kind, "course_id": course_id}

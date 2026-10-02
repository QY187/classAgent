from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...shared.models import Course, CourseMaterial, Lesson

MODELS = {"course": Course, "lesson": Lesson, "material": CourseMaterial}


def raw_get(db: Session, model, identity: str, lock=False):
    query = select(model).where(model.id == identity).execution_options(include_deleted=True, populate_existing=True)
    return db.scalar(query.with_for_update() if lock else query)


def owned_item(db: Session, kind: str, identity: str, username: str):
    model = MODELS.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="回收站项目不存在")
    item = raw_get(db, model, identity)
    if item is None:
        raise HTTPException(status_code=404, detail="回收站项目不存在")
    # 所有同一课程的回收站操作先锁课程，再锁具体对象。
    course = raw_get(db, Course, identity if kind == "course" else item.course_id, lock=True)
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(status_code=404, detail="回收站项目不存在")
    item = raw_get(db, model, identity, lock=True)
    if item is None:
        raise HTTPException(status_code=404, detail="回收站项目不存在")
    lesson = raw_get(db, Lesson, item.lesson_id) if kind == "material" and item.lesson_id else None
    return item, course, lesson

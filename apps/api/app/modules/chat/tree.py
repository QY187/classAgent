from sqlalchemy import select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...shared.models import Course, Lesson


def lesson_tree(db: Session, username: str) -> list[dict]:
    rows = db.execute(select(Lesson, Course.name).join(Course, Course.id == Lesson.course_id).where(
        Course.owner_id == user_id_for_username(db, username)
    ).order_by(Course.created_at.desc(), Course.id, Lesson.sort_order.asc().nulls_last(), Lesson.lesson_date.desc().nulls_last(), Lesson.created_at.desc(), Lesson.id))
    return [{"id": lesson.id, "title": lesson.title, "course_id": lesson.course_id, "course_name": name} for lesson, name in rows]

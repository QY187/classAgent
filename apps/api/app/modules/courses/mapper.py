from sqlalchemy import select
from sqlalchemy.orm import Session

from ...shared.models import Course, Lesson


def save_course(db: Session, course: Course) -> Course:
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def find_course(db: Session, course_id: str) -> Course | None:
    return db.get(Course, course_id)


def find_courses(db: Session, owner_id: str) -> list[Course]:
    return list(db.scalars(
        select(Course).where(Course.owner_id == owner_id).order_by(Course.created_at.desc())
    ))


def save_lesson(db: Session, lesson: Lesson) -> Lesson:
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


def find_lessons(db: Session, course_id: str) -> list[Lesson]:
    return list(db.scalars(select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.created_at.desc())))

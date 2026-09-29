from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...models import Course, Lesson
from ...schemas import CourseCreate, LessonCreate
from . import mapper


def create_course(db: Session, payload: CourseCreate) -> Course:
    return mapper.save_course(db, Course(name=payload.name, semester=payload.semester))


def list_courses(db: Session) -> list[Course]:
    return mapper.find_courses(db)


def create_lesson(db: Session, course_id: str, payload: LessonCreate) -> Lesson:
    if mapper.find_course(db, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return mapper.save_lesson(db, Lesson(course_id=course_id, title=payload.title, lesson_date=payload.lesson_date))


def list_lessons(db: Session, course_id: str) -> list[Lesson]:
    if mapper.find_course(db, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return mapper.find_lessons(db, course_id)

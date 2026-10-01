from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...shared.models import Course, Lesson
from ...shared.schemas import CourseCreate, LessonCreate
from . import mapper


def create_course(db: Session, payload: CourseCreate, owner_username: str) -> Course:
    return mapper.save_course(db, Course(owner_id=user_id_for_username(db, owner_username), owner_username=owner_username, name=payload.name, semester=payload.semester))


def list_courses(db: Session, owner_username: str) -> list[Course]:
    return mapper.find_courses(db, user_id_for_username(db, owner_username))


def create_lesson(db: Session, course_id: str, payload: LessonCreate, owner_username: str) -> Lesson:
    course = mapper.find_course(db, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    return mapper.save_lesson(db, Lesson(course_id=course_id, title=payload.title, lesson_date=payload.lesson_date))


def list_lessons(db: Session, course_id: str, owner_username: str) -> list[Lesson]:
    course = mapper.find_course(db, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    return mapper.find_lessons(db, course_id)

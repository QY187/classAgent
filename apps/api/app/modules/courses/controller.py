from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...shared.models import Course, Lesson
from ...shared.schemas import CourseCreate, CourseRead, LessonCreate, LessonRead
from . import service


router = APIRouter(tags=["courses"])


@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    return service.create_course(db, payload)


@router.get("/courses", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return service.list_courses(db)


@router.post("/courses/{course_id}/lessons", response_model=LessonRead, status_code=201)
def create_lesson(course_id: str, payload: LessonCreate, db: Session = Depends(get_db)) -> Lesson:
    return service.create_lesson(db, course_id, payload)


@router.get("/courses/{course_id}/lessons", response_model=list[LessonRead])
def list_lessons(course_id: str, db: Session = Depends(get_db)) -> list[Lesson]:
    return service.list_lessons(db, course_id)

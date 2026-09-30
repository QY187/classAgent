from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from ...shared.schemas import CourseCreate, CourseRead, LessonCreate, LessonRead
from . import service


router = APIRouter(tags=["courses"], dependencies=[Depends(get_current_user)])


@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    return service.create_course(db, payload, username)


@router.get("/courses", response_model=list[CourseRead])
def list_courses(username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> list:
    return service.list_courses(db, username)


@router.post("/courses/{course_id}/lessons", response_model=LessonRead, status_code=201)
def create_lesson(course_id: str, payload: LessonCreate, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    return service.create_lesson(db, course_id, payload, username)


@router.get("/courses/{course_id}/lessons", response_model=list[LessonRead])
def list_lessons(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> list:
    return service.list_lessons(db, course_id, username)

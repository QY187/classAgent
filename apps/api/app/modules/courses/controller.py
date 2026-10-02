from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from ...shared.schemas import CourseCreate, CourseRead, CourseUpdate, LessonCreate, LessonRead, LessonUpdate
from . import service


router = APIRouter(tags=["courses"], dependencies=[Depends(get_current_user)])


@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    return service.create_course(db, payload, username)


@router.get("/courses", response_model=list[CourseRead])
def list_courses(username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> list:
    return service.list_courses(db, username)


@router.get("/courses/{course_id}/progress")
def get_course_progress(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.get_course_progress(db, course_id, username)


@router.patch("/courses/{course_id}", response_model=CourseRead)
def update_course(course_id: str, payload: CourseUpdate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_course(db, course_id, payload, username)


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_course(db, course_id, username)


@router.post("/courses/{course_id}/lessons", response_model=LessonRead, status_code=201)
def create_lesson(course_id: str, payload: LessonCreate, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    return service.create_lesson(db, course_id, payload, username)


@router.get("/courses/{course_id}/lessons", response_model=list[LessonRead])
def list_lessons(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> list:
    return service.list_lessons(db, course_id, username)


@router.patch("/lessons/{lesson_id}", response_model=LessonRead)
def update_lesson(lesson_id: str, payload: LessonUpdate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_lesson(db, lesson_id, payload, username)


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_lesson(db, lesson_id, username)

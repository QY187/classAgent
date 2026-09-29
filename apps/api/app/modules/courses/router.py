from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Course, Lesson
from ...schemas import CourseCreate, CourseRead, LessonCreate, LessonRead
from fastapi import HTTPException


router = APIRouter(tags=["courses"])


@router.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    course = Course(name=payload.name, semester=payload.semester)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("/courses", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(db.scalars(select(Course).order_by(Course.created_at.desc())))


@router.post("/courses/{course_id}/lessons", response_model=LessonRead, status_code=201)
def create_lesson(course_id: str, payload: LessonCreate, db: Session = Depends(get_db)) -> Lesson:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    lesson = Lesson(course_id=course_id, title=payload.title, lesson_date=payload.lesson_date)
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


@router.get("/courses/{course_id}/lessons", response_model=list[LessonRead])
def list_lessons(course_id: str, db: Session = Depends(get_db)) -> list[Lesson]:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return list(db.scalars(select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.created_at.desc())))

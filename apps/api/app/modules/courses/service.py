from fastapi import HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...infrastructure.storage import delete_file
from ...shared.models import AudioFile, Course, CourseMaterial, Lesson, LessonSummary
from ...shared.schemas import CourseCreate, CourseUpdate, LessonCreate, LessonUpdate
from . import mapper


def create_course(db: Session, payload: CourseCreate, owner_username: str) -> Course:
    return mapper.save_course(db, Course(owner_id=user_id_for_username(db, owner_username), owner_username=owner_username, name=payload.name, semester=payload.semester))


def list_courses(db: Session, owner_username: str) -> list[Course]:
    return mapper.find_courses(db, user_id_for_username(db, owner_username))


def update_course(db: Session, course_id: str, payload: CourseUpdate, owner_username: str) -> Course:
    course = mapper.find_course(db, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="课程名称不能为空")
    course.name = name
    course.semester = payload.semester.strip() or None if payload.semester else None
    db.commit()
    db.refresh(course)
    return course


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


def update_lesson(db: Session, lesson_id: str, payload: LessonUpdate, owner_username: str) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    course = mapper.find_course(db, lesson.course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课次不存在")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="课次标题不能为空")
    lesson.title = title
    lesson.lesson_date = payload.lesson_date or None
    db.commit()
    db.refresh(lesson)
    return lesson


def _check_deletable(db: Session, lesson_ids: list[str]) -> None:
    if not lesson_ids:
        return
    active_lesson = db.scalar(select(Lesson.id).where(Lesson.id.in_(lesson_ids), Lesson.status == "transcribing").limit(1))
    active_summary = db.scalar(select(LessonSummary.id).where(LessonSummary.lesson_id.in_(lesson_ids), LessonSummary.status == "generating").limit(1))
    if active_lesson or active_summary:
        raise HTTPException(status_code=409, detail="有课次正在转写或生成纪要，请处理完成后再删除")


def delete_lesson(db: Session, lesson_id: str, owner_username: str) -> None:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or lesson.course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课次不存在")
    _check_deletable(db, [lesson_id])
    keys = list(db.scalars(select(AudioFile.object_key).where(AudioFile.lesson_id == lesson_id)))
    keys += list(db.scalars(select(CourseMaterial.object_key).where(CourseMaterial.lesson_id == lesson_id)))
    for key in keys:
        delete_file(key)
    db.execute(delete(CourseMaterial).where(CourseMaterial.lesson_id == lesson_id))
    db.delete(lesson)
    db.commit()


def delete_course(db: Session, course_id: str, owner_username: str) -> None:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    lesson_ids = list(db.scalars(select(Lesson.id).where(Lesson.course_id == course_id)))
    _check_deletable(db, lesson_ids)
    keys = list(db.scalars(select(AudioFile.object_key).where(AudioFile.lesson_id.in_(lesson_ids)))) if lesson_ids else []
    keys += list(db.scalars(select(CourseMaterial.object_key).where(CourseMaterial.course_id == course_id)))
    for key in keys:
        delete_file(key)
    db.delete(course)
    db.commit()

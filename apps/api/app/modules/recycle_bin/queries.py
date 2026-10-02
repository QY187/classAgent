from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...shared.models import Course, CourseMaterial, Lesson


def list_items(db: Session, username: str) -> list[dict]:
    owner_id = user_id_for_username(db, username)
    items = []
    courses = db.scalars(select(Course).where(Course.owner_id == owner_id, Course.deleted_at.is_not(None))
                         .execution_options(include_deleted=True))
    for course in courses:
        items.append({"id": course.id, "kind": "course", "title": course.name, "course_name": course.name,
                      "lesson_title": None, "deleted_at": course.deleted_at})
    lessons = db.execute(select(Lesson, Course).join(Course, Lesson.course_id == Course.id).where(
        Course.owner_id == owner_id, Course.deleted_at.is_(None), Lesson.deleted_at.is_not(None)
    ).execution_options(include_deleted=True))
    for lesson, course in lessons:
        items.append({"id": lesson.id, "kind": "lesson", "title": lesson.title, "course_name": course.name,
                      "lesson_title": lesson.title, "deleted_at": lesson.deleted_at})
    materials = db.execute(select(CourseMaterial, Course, Lesson).join(Course, CourseMaterial.course_id == Course.id)
        .outerjoin(Lesson, CourseMaterial.lesson_id == Lesson.id).where(
            Course.owner_id == owner_id, Course.deleted_at.is_(None), CourseMaterial.deleted_at.is_not(None),
            or_(CourseMaterial.lesson_id.is_(None), Lesson.deleted_at.is_(None))
        ).execution_options(include_deleted=True))
    for material, course, lesson in materials:
        items.append({"id": material.id, "kind": "material", "title": material.filename, "course_name": course.name,
                      "lesson_title": lesson.title if lesson else None, "deleted_at": material.deleted_at})
    return sorted(items, key=lambda item: (item["deleted_at"], item["id"]), reverse=True)

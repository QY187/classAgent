from pathlib import PureWindowsPath
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...infrastructure.storage import upload_file
from ...shared.models import Course, CourseMaterial, Lesson


MAX_MATERIAL_BYTES = 25 * 1024 * 1024
ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _owned_course(db: Session, course_id: str, username: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def list_materials(db: Session, course_id: str, username: str) -> list[CourseMaterial]:
    _owned_course(db, course_id, username)
    return list(db.scalars(select(CourseMaterial).where(CourseMaterial.course_id == course_id).order_by(CourseMaterial.created_at.desc(), CourseMaterial.id.desc())))


def upload_material(db: Session, course_id: str, lesson_id: str | None, file: UploadFile, username: str) -> CourseMaterial:
    _owned_course(db, course_id, username)
    if lesson_id and db.scalar(select(Lesson.id).where(Lesson.id == lesson_id, Lesson.course_id == course_id)) is None:
        raise HTTPException(status_code=400, detail="所选课次不属于当前课程")

    filename = PureWindowsPath(file.filename or "").name
    suffix = PureWindowsPath(filename).suffix.lower()
    if not filename or len(filename) > 255 or suffix not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 PDF、PPT、Word、图片和文本资料，文件名不超过 255 个字符")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0 or size > MAX_MATERIAL_BYTES:
        raise HTTPException(status_code=400, detail="资料大小须在 1 字节至 25 MB 之间")

    object_key = f"materials/{course_id}/{uuid4()}{suffix}"
    content_type = ALLOWED_TYPES[suffix]
    upload_file(object_key, file.file, size, content_type)
    material = CourseMaterial(course_id=course_id, lesson_id=lesson_id, filename=filename,
                              content_type=content_type, object_key=object_key, size_bytes=size)
    db.add(material)
    db.commit()
    db.refresh(material)
    return material

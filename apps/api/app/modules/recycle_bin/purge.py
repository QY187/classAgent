from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ...shared.models import AudioFile, CourseMaterial, Lesson, PendingFileDeletion
from .file_cleanup import clean_pending_files
from .mapper import MODELS, owned_item
from .service import ensure_idle


def purge_item(db: Session, kind: str, identity: str, username: str) -> dict:
    item, course, lesson = owned_item(db, kind, identity, username)
    if item.deleted_at is None:
        raise HTTPException(status_code=409, detail="只能彻底删除回收站中的内容")
    if (kind != "course" and course.deleted_at is not None) or (lesson and lesson.deleted_at is not None):
        raise HTTPException(status_code=409, detail="所属课程或课次也在回收站，请先恢复父级或直接删除父级")
    if kind == "material":
        keys = [item.object_key]
    else:
        lesson_ids = [identity] if kind == "lesson" else list(db.scalars(
            select(Lesson.id).where(Lesson.course_id == identity).execution_options(include_deleted=True)))
        ensure_idle(db, lesson_ids)
        audio = AudioFile.__table__
        materials = CourseMaterial.__table__
        material_scope = materials.c.lesson_id == identity if kind == "lesson" else materials.c.course_id == identity
        keys = list(db.scalars(select(audio.c.object_key).where(audio.c.lesson_id.in_(lesson_ids))))
        keys += list(db.scalars(select(materials.c.object_key).where(material_scope)))
        # 课次资料的外键为 SET NULL，彻底删除课次时显式清理，避免变成无归属资料。
        db.execute(delete(materials).where(material_scope))
    for key in set(keys):
        db.add(PendingFileDeletion(user_id=course.owner_id, object_key=key))
    db.flush()
    table = MODELS[kind].__table__
    db.execute(delete(table).where(table.c.id == identity))
    db.commit()
    db.expunge_all()
    return clean_pending_files(db, username)

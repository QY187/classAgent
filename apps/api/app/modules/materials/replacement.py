"""显式替换文件：暂存新原件，成功后由解析任务与索引一并发布。"""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from ...core.ownership import user_id_for_username
from ...infrastructure.storage import upload_file
from ...shared.models import MaterialProcessing, MaterialReplacement, PendingFileDeletion, new_id, now_utc
from .extraction import SUPPORTED_SUFFIXES
from .locking import lock_material
from .processing import dispatch_one, owned_material
from .service import validate_material_file


def replace_material(db, course_id, material_id, file, username):
    owned_material(db, course_id, material_id, username)
    filename, suffix, size, content_type = validate_material_file(file)
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(415, "替换问答资料请上传文字型 PDF、PPTX、DOCX、TXT 或 Markdown")
    owner_id = user_id_for_username(db, username)
    db.rollback()
    object_key = f"materials/{course_id}/{uuid4()}{suffix}"
    try:
        upload_file(object_key, file.file, size, content_type)
        # 上传期间可以被删除或替换，因此存储完成后必须重新鉴权并获取锁。
        material, _ = lock_material(db, course_id, material_id, username)
        from .service import ensure_unique_filename
        ensure_unique_filename(db, course_id, material.lesson_id, filename, exclude_id=material_id)
        pending = db.get(MaterialReplacement, material_id)
        if pending is not None:
            db.add(PendingFileDeletion(user_id=owner_id, object_key=pending.object_key))
        else:
            pending = MaterialReplacement(material_id=material_id)
            db.add(pending)
        pending.filename, pending.object_key = filename, object_key
        pending.content_type, pending.size_bytes = content_type, size
        pending.created_at = now_utc()
        state = db.scalar(select(MaterialProcessing).where(MaterialProcessing.material_id == material_id)
                          .execution_options(populate_existing=True))
        if state is None:
            state = MaterialProcessing(material_id=material_id)
            db.add(state)
        generation = new_id()
        state.generation, state.status = generation, "queued"
        state.error_message, state.updated_at = None, now_utc()
        db.commit()
    except Exception as exc:
        db.rollback()
        # 注册失败或上传部分成功均交给既有可重试文件清理队列，不能误删当前原件。
        db.add(PendingFileDeletion(user_id=owner_id, object_key=object_key))
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "替换文件保存或登记失败，请重试") from exc
    dispatch_one(material_id, generation)
    return material

"""课件解析任务：数据库登记、队列补投递和版本原子切换。"""
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ...core.embeddings import embed_texts
from ...core.visibility import visible_get
from ...infrastructure.storage import materialize_file
from ...shared.models import CourseMaterial, MaterialChunk, MaterialProcessing, new_id, now_utc
from .extraction import ExtractionError, SUPPORTED_SUFFIXES, extract_units, make_material_chunks


def enqueue_material(db: Session, material: CourseMaterial) -> MaterialProcessing:
    state = db.get(MaterialProcessing, material.id)
    if state and state.status in {"queued", "processing", "indexing"}:
        return state
    if state is None:
        state = MaterialProcessing(material_id=material.id)
        db.add(state)
    state.generation = new_id()
    state.error_message = None
    state.status = "queued" if Path(material.filename).suffix.lower() in SUPPORTED_SUFFIXES else "unsupported"
    if state.status == "unsupported":
        state.error_message = "该格式可预览或下载，问答解析请上传文字型 PDF、PPTX、DOCX、TXT 或 Markdown。"
    state.updated_at = now_utc()
    db.commit()
    if state.status == "queued":
        dispatch_one(material.id, state.generation)
    return state


def dispatch_one(material_id, generation):
    from ...infrastructure.tasks import process_material
    try:
        process_material.apply_async(args=[material_id, generation], retry=False)
    except Exception:
        # 登记已经提交，由 beat 补发；不因队列故障撤销已保存文件。
        return False
    return True


def dispatch_pending_materials(db: Session) -> int:
    cutoff = now_utc() - timedelta(minutes=10)
    stale = list(db.scalars(select(MaterialProcessing).join(CourseMaterial).where(
        MaterialProcessing.status.in_(["processing", "indexing"]), MaterialProcessing.updated_at < cutoff).limit(50)))
    for state in stale:
        state.generation = new_id()
        state.status = "queued"
        state.updated_at = now_utc()
    db.commit()
    pending = list(db.scalars(select(MaterialProcessing).join(CourseMaterial).where(
        MaterialProcessing.status == "queued").order_by(MaterialProcessing.updated_at).limit(50)))
    return sum(dispatch_one(state.material_id, state.generation) for state in pending)


def process_material_content(db: Session, material_id: str, generation: str) -> int:
    material = visible_get(db, CourseMaterial, material_id)
    if material is None:
        return 0
    claimed = db.execute(update(MaterialProcessing).where(
        MaterialProcessing.material_id == material_id, MaterialProcessing.generation == generation,
        MaterialProcessing.status == "queued").values(status="processing", updated_at=now_utc()))
    db.commit()
    if claimed.rowcount != 1:
        return 0
    path = None
    remove = False
    try:
        filename, object_key = material.filename, material.object_key
        db.rollback()
        path, remove = materialize_file(object_key)
        chunks = make_material_chunks(extract_units(path, filename))
        indexing = db.execute(update(MaterialProcessing).where(
            MaterialProcessing.material_id == material_id, MaterialProcessing.generation == generation,
            MaterialProcessing.status == "processing").values(status="indexing", updated_at=now_utc()))
        db.commit()
        if indexing.rowcount != 1:
            return 0
        vectors = []
        for start in range(0, len(chunks), 20):
            # 大文件可能分多批，旧任务被换代后不再继续产生向量调用。
            active = db.scalar(select(MaterialProcessing.generation).where(
                MaterialProcessing.material_id == material_id, MaterialProcessing.status == "indexing"))
            db.rollback()
            if active != generation or visible_get(db, CourseMaterial, material_id) is None:
                return 0
            db.rollback()
            vectors.extend(embed_texts([item["content"] for item in chunks[start:start + 20]]))
        if len(vectors) != len(chunks) or any(len(vector) != 1536 for vector in vectors):
            raise ValueError("invalid embedding batch")
        db.expire_all()
        if visible_get(db, CourseMaterial, material_id) is None:
            return 0
        switched = db.execute(update(MaterialProcessing).where(
            MaterialProcessing.material_id == material_id, MaterialProcessing.generation == generation,
            MaterialProcessing.status == "indexing").values(
                status="ready", active_version=generation, error_message=None, updated_at=now_utc()))
        if switched.rowcount != 1:
            db.rollback()
            return 0
        db.execute(delete(MaterialChunk).where(MaterialChunk.material_id == material_id))
        db.add_all(MaterialChunk(material_id=material_id, version=generation, embedding=vector, **chunk)
                   for chunk, vector in zip(chunks, vectors))
        db.commit()
        return len(chunks)
    except Exception as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ExtractionError) else "课件处理失败，请重试；如持续失败，请检查文件或联系管理员。"
        db.execute(update(MaterialProcessing).where(
            MaterialProcessing.material_id == material_id, MaterialProcessing.generation == generation,
            MaterialProcessing.status.in_(["processing", "indexing"])).values(status="failed", error_message=message, updated_at=now_utc()))
        db.commit()
        return 0
    finally:
        if path is not None and remove:
            Path(path).unlink(missing_ok=True)


def material_read(db: Session, material: CourseMaterial) -> dict:
    state = db.get(MaterialProcessing, material.id)
    return {key: getattr(material, key) for key in (
        "id", "course_id", "lesson_id", "filename", "content_type", "source", "status", "size_bytes", "created_at")} | {
        "processing_status": state.status if state else "stored",
        "processing_error": state.error_message if state else None,
        "indexed": bool(state and state.active_version),
    }


def owned_material(db, course_id, material_id, username):
    from .service import _owned_course
    _owned_course(db, course_id, username)
    material = visible_get(db, CourseMaterial, material_id)
    if material is None or material.course_id != course_id:
        raise HTTPException(404, "资料不存在")
    return material

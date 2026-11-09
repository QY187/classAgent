"""课件活动版本读取、定位与来源有效性检查。"""
from sqlalchemy import select

from ...shared.models import CourseMaterial, MaterialChunk, MaterialProcessing
from .processing import material_read, owned_material


def active_chunks():
    return select(MaterialChunk).join(CourseMaterial, CourseMaterial.id == MaterialChunk.material_id).join(
        MaterialProcessing, MaterialProcessing.material_id == CourseMaterial.id).where(
        MaterialChunk.version == MaterialProcessing.active_version)


def locator_label(kind, number):
    return f"第 {number} " + {"page": "页", "slide": "张幻灯片", "paragraph": "段"}.get(kind, "处")


def chunk_read(chunk, material):
    return {"chunk_id": chunk.id, "material_id": material.id, "course_id": material.course_id,
            "lesson_id": material.lesson_id, "filename": material.filename, "version": chunk.version,
            "position": chunk.position, "locator_type": chunk.locator_type, "locator_number": chunk.locator_number,
            "locator_label": locator_label(chunk.locator_type, chunk.locator_number), "text": chunk.content,
            "source_type": "material"}


def read_content(db, course_id, material_id, username, *, offset=0, limit=10, version=None):
    material = owned_material(db, course_id, material_id, username)
    rows = list(db.scalars(active_chunks().where(MaterialChunk.material_id == material_id,
        MaterialChunk.position >= offset).order_by(MaterialChunk.position).limit(limit + 1)))
    state = db.get(MaterialProcessing, material_id)
    return {"material": material_read(db, material),
            "source_status": "changed" if version and (not state or state.active_version != version) else "current",
            "items": [chunk_read(row, material) for row in rows[:limit]],
            "next_offset": rows[limit].position if len(rows) > limit else None}


def current_material_chunk(db, identity):
    return db.scalar(active_chunks().where(MaterialChunk.id == identity).execution_options(populate_existing=True))


def refresh_material_citation(db, citation, username):
    """旧回答保留快照，但不把已删除或换版的资料显示为有效来源。"""
    if citation.get("source_type") != "material":
        return citation
    from fastapi import HTTPException
    try:
        material = owned_material(db, citation.get("course_id"), citation.get("material_id"), username)
    except HTTPException:
        return {**citation, "source_status": "unavailable"}
    chunk = current_material_chunk(db, citation.get("chunk_id"))
    current = (chunk is not None and chunk.material_id == material.id and chunk.version == citation.get("version")
               and citation.get("snippet", "") in chunk.content)
    return {**citation, "source_status": "current" if current else "changed"}

"""仅使用课程内课件活动版本，并保存可核对的引用快照。"""
import json
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from ...shared.models import CourseMaterial, Lesson, MaterialChunk
from ..materials.content import active_chunks, chunk_read, refresh_material_citation
from ..materials.processing import owned_material


def material_sources(db, course_id, lesson_ids, material_ids, username):
    query = select(CourseMaterial).where(CourseMaterial.course_id == course_id)
    if lesson_ids:
        query = query.where(CourseMaterial.lesson_id.in_(lesson_ids))
    materials = list(db.scalars(query.order_by(CourseMaterial.created_at, CourseMaterial.id)))
    # 课次回收时，其资料也不得被整门课程出题读到。
    materials = [m for m in materials if not m.lesson_id or db.scalar(select(Lesson.id).where(Lesson.id == m.lesson_id))]
    if material_ids:
        allowed = {m.id for m in materials}
        if set(material_ids) - allowed:
            raise HTTPException(400, "所选课件不存在或不属于出题范围")
        materials = [m for m in materials if m.id in material_ids]
    sources = []
    for material in materials:
        owned_material(db, course_id, material.id, username)
        rows = list(db.scalars(active_chunks().where(CourseMaterial.id == material.id).order_by(MaterialChunk.position)))
        if material_ids and not rows:
            raise HTTPException(400, "所选课件尚未解析，请先在资料中加入问答并等待完成")
        for row in rows:
            if row.content.strip():
                sources.append(SimpleNamespace(id=row.id, material_id=material.id, lesson_id=material.lesson_id,
                    text=row.content, start_ms=0, citation=chunk_read(row, material)))
    if not sources:
        raise HTTPException(400, "当前范围没有已解析课件，请先上传文字型课件并加入问答")
    return sources


def validate_material_source(db, source, evidence, username):
    material = owned_material(db, source.citation["course_id"], source.material_id, username)
    db.refresh(material)
    if material.lesson_id != source.lesson_id:
        raise HTTPException(400, "课件所属课次已变化，请重新选择范围")
    citation = {key: value for key, value in source.citation.items() if key != "text"}
    citation["snippet"] = evidence
    current = refresh_material_citation(db, citation, username)
    if current["source_status"] != "current":
        raise HTTPException(400, "出题课件已删除、替换或原文已变化，请重新生成")
    return citation


def material_evidence(db, question, username):
    if not question.source_material_json:
        return {}
    citation = json.loads(question.source_material_json)
    citation = refresh_material_citation(db, citation, username)
    return {"source_material": citation}

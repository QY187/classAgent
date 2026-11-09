"""受对话范围限制的课件列表与原文读取工具。"""
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from ...shared.models import MaterialChunk, MaterialProcessing
from ..materials.content import active_chunks, chunk_read
from ..materials.processing import owned_material, material_read
from ..materials.service import list_materials


def source_preference(context):
    return context.action_hints.get("source_type", "all")


def check_material(db, context, course_id, material_id):
    from .tools import check_course, check_lesson
    check_course(db, context, course_id)
    material = owned_material(db, course_id, material_id, context.username)
    if context.lesson_id:
        check_lesson(db, context, context.lesson_id)
        if material.lesson_id != context.lesson_id:
            raise HTTPException(404, "资料不存在")
    if source_preference(context) == "transcript":
        raise HTTPException(403, "本次问题限定课堂录音来源")
    return material


def list_course_materials(db, context, args):
    from .tools import check_course, page
    check_course(db, context, args.course_id)
    rows = [item for item in list_materials(db, args.course_id, context.username)
            if (not context.lesson_id or item.lesson_id == context.lesson_id) and args.query.casefold() in item.filename.casefold()]
    return jsonable_encoder({"course_id": args.course_id, **page([material_read(db, item) for item in rows], args.offset, args.limit)})


def get_material_content(db, context, args):
    material = check_material(db, context, args.course_id, args.material_id)
    query = active_chunks().where(MaterialChunk.material_id == material.id, MaterialChunk.position >= args.offset)
    if args.locator_number is not None:
        query = query.where(MaterialChunk.locator_number == args.locator_number)
    rows = list(db.scalars(query.order_by(MaterialChunk.position).limit(args.limit + 1)))
    state = db.get(MaterialProcessing, material.id)
    return {"course_id": args.course_id, "material_id": material.id, "filename": material.filename,
            "processing_status": state.status if state else "stored", "indexed": bool(state and state.active_version),
            "items": [chunk_read(row, material) for row in rows[:args.limit]],
            "next_offset": rows[args.limit].position if len(rows) > args.limit else None,
            "content_limitations": "仅提取可读取的文字，未识别图片、图表和复杂公式；课件内容不代表老师课堂原话。"}

"""仅更新本次已查询到的、当前范围中的知识点状态。"""
from fastapi import HTTPException
from ...core.visibility import visible_get
from ...shared.models import ReviewCard
from .tools import check_lesson
from .actions import execute_action


def update_knowledge_status(db, context, args):
    card = visible_get(db, ReviewCard, args.knowledge_point_id)
    if card is None:
        raise HTTPException(404, "知识点不存在")
    lesson = check_lesson(db, context, card.lesson_id)
    if lesson.course_id != card.course_id:
        raise HTTPException(404, "知识点不存在")
    return execute_action(db, context, "update_knowledge_status", args)

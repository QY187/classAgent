"""归档仅收起对话，不删除消息，也不改变消息时间。"""
from fastapi import HTTPException
from sqlalchemy import select, update, func, or_
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...shared.models import ChatConversation, Course, Lesson
from .access import owned_conversation
from .conversations import conversation_read
from .generation import is_generating


def set_archived(db: Session, identity: str, username: str, archived: bool) -> dict:
    item = owned_conversation(db, identity, username, lock=True)
    if is_generating(item):
        raise HTTPException(409, "请等待回答完成后归档或恢复对话")
    db.execute(update(ChatConversation).where(ChatConversation.id == item.id).values(
        is_archived=archived, updated_at=ChatConversation.updated_at))
    db.commit(); db.refresh(item)
    return conversation_read(item)


def list_archived(db: Session, username: str) -> list[dict]:
    owner = user_id_for_username(db, username)
    rows = db.execute(select(ChatConversation, Course.name, Lesson.title)
        .outerjoin(Lesson, ChatConversation.lesson_id == Lesson.id)
        .outerjoin(Course, func.coalesce(ChatConversation.course_id, Lesson.course_id) == Course.id)
        .where(ChatConversation.user_id == owner, ChatConversation.is_archived.is_(True),
            or_(Course.owner_id == owner, (ChatConversation.course_id.is_(None) & ChatConversation.lesson_id.is_(None))))
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id))
    return [{**conversation_read(item), "course_name": course or "主对话", "lesson_title": lesson}
            for item, course, lesson in rows]

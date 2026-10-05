from sqlalchemy import select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...shared.models import ChatConversation
from .access import owned_lesson
from .generation import is_generating


def conversation_read(item: ChatConversation) -> dict:
    return {"id": item.id, "lesson_id": item.lesson_id, "title": item.title,
            "created_at": item.created_at, "updated_at": item.updated_at, "generating": is_generating(item)}


def create_conversation(db: Session, lesson_id: str, username: str) -> dict:
    owned_lesson(db, lesson_id, username, lock=True)
    item = ChatConversation(lesson_id=lesson_id, user_id=user_id_for_username(db, username))
    db.add(item); db.commit(); db.refresh(item)
    return conversation_read(item)


def list_conversations(db: Session, lesson_id: str, username: str) -> list[dict]:
    owned_lesson(db, lesson_id, username)
    return [conversation_read(item) for item in db.scalars(select(ChatConversation).where(
        ChatConversation.lesson_id == lesson_id, ChatConversation.user_id == user_id_for_username(db, username)
    ).order_by(ChatConversation.updated_at.desc(), ChatConversation.id))]

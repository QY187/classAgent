from sqlalchemy import select, or_, update
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ...core.ownership import user_id_for_username
from ...shared.models import ChatConversation, Lesson
from .access import owned_lesson, owned_course, owned_conversation
from .generation import is_generating


def conversation_read(item: ChatConversation) -> dict:
    return {"id": item.id, "lesson_id": item.lesson_id, "course_id": item.course_id,
            "scope": "lesson" if item.lesson_id else "course" if item.course_id else "global", "title": item.title,
            "is_pinned": item.is_pinned, "is_archived": item.is_archived, "created_at": item.created_at, "updated_at": item.updated_at, "generating": is_generating(item)}


def create_conversation(db: Session, lesson_id: str, username: str) -> dict:
    owned_lesson(db, lesson_id, username, lock=True)
    item = ChatConversation(lesson_id=lesson_id, user_id=user_id_for_username(db, username))
    db.add(item); db.commit(); db.refresh(item)
    return conversation_read(item)


def create_course_conversation(db: Session, course_id: str, username: str) -> dict:
    owned_course(db, course_id, username, lock=True)
    item = ChatConversation(course_id=course_id, user_id=user_id_for_username(db, username))
    db.add(item); db.commit(); db.refresh(item)
    return conversation_read(item)


def create_global_conversation(db: Session, username: str) -> dict:
    item = ChatConversation(user_id=user_id_for_username(db, username))
    db.add(item); db.commit(); db.refresh(item)
    return conversation_read(item)


def list_global_conversations(db: Session, username: str) -> list[dict]:
    return [conversation_read(item) for item in db.scalars(select(ChatConversation).where(
        ChatConversation.is_archived.is_(False),
        ChatConversation.user_id == user_id_for_username(db, username),
        ChatConversation.course_id.is_(None), ChatConversation.lesson_id.is_(None)
    ).order_by(ChatConversation.is_pinned.desc(), ChatConversation.updated_at.desc(), ChatConversation.id))]


def list_course_conversations(db: Session, course_id: str, username: str, include_lessons: bool = False) -> list[dict]:
    owned_course(db, course_id, username)
    scope = ChatConversation.course_id == course_id
    if include_lessons:
        scope = or_(scope, ChatConversation.lesson_id.in_(select(Lesson.id).where(Lesson.course_id == course_id)))
    return [conversation_read(item) for item in db.scalars(select(ChatConversation).where(
        ChatConversation.is_archived.is_(False),
        scope, ChatConversation.user_id == user_id_for_username(db, username)
    ).order_by(ChatConversation.is_pinned.desc(), ChatConversation.updated_at.desc(), ChatConversation.id))]


def list_conversations(db: Session, lesson_id: str, username: str) -> list[dict]:
    owned_lesson(db, lesson_id, username)
    return [conversation_read(item) for item in db.scalars(select(ChatConversation).where(
        ChatConversation.is_archived.is_(False),
        ChatConversation.lesson_id == lesson_id, ChatConversation.user_id == user_id_for_username(db, username)
    ).order_by(ChatConversation.is_pinned.desc(), ChatConversation.updated_at.desc(), ChatConversation.id))]


def rename_conversation(db: Session, identity: str, username: str, title: str) -> dict:
    title = title.strip()
    if not 1 <= len(title) <= 200:
        raise HTTPException(422, "对话标题需要 1 到 200 字")
    item = owned_conversation(db, identity, username, lock=True)
    if is_generating(item):
        raise HTTPException(409, "请等待回答完成后修改标题")
    item.title = title
    db.commit(); db.refresh(item)
    return conversation_read(item)


def set_conversation_pin(db: Session, identity: str, username: str, is_pinned: bool) -> dict:
    item = owned_conversation(db, identity, username, lock=True)
    # 置顶不是新消息，不触发 updated_at 自动更新；取消后回到原来的时间顺序。
    db.execute(update(ChatConversation).where(ChatConversation.id == item.id).values(
        is_pinned=is_pinned, updated_at=ChatConversation.updated_at
    ))
    db.commit(); db.refresh(item)
    return conversation_read(item)

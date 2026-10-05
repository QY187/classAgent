"""消息发送、幂等请求和失败恢复；模型检索由独立 RAG 服务承担。"""
import json
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from ...shared.models import ChatConversation, ChatMessage, Lesson, new_id, now_utc
from ..rag.service import ask_course
from .access import owned_conversation
from .messages import read_messages
from .generation import is_generating
from .context import recent_context


def _finish_failed(db: Session, conversation_id: str, request_id: str, token: str, error: str):
    db.rollback()
    conversations = ChatConversation.__table__
    updated = db.execute(update(conversations).where(conversations.c.id == conversation_id,
        conversations.c.generation_token == token).values(generation_token=None, generating_at=None))
    if updated.rowcount:
        messages = ChatMessage.__table__
        db.execute(update(messages).where(messages.c.conversation_id == conversation_id,
            messages.c.request_id == request_id, messages.c.role == "user", messages.c.status == "pending"
        ).values(status="failed", error_message=error))
    db.commit()


def send_message(db: Session, conversation_id: str, username: str, content: str, request_id: str) -> dict:
    question = content.strip()
    if not 2 <= len(question) <= 1000:
        raise HTTPException(422, "请输入 2 到 1000 字的问题")
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    existing = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.request_id == request_id, ChatMessage.role == "user"))
    if existing is not None and existing.content != question:
        raise HTTPException(409, "请求编号已用于其他问题")
    if existing is not None and existing.status == "completed":
        db.commit()
        return read_messages(db, conversation_id, username)
    if is_generating(conversation):
        raise HTTPException(409, "这个对话正在回答，请稍后再试")
    # 回收中断或进程退出后，旧占用会过期；旧消息可由用户主动重试。
    db.execute(update(ChatMessage).where(ChatMessage.conversation_id == conversation_id, ChatMessage.status == "pending")
        .values(status="failed", error_message="上次回答中断，请重试"))
    last_position = db.scalar(select(func.max(ChatMessage.position)).where(ChatMessage.conversation_id == conversation_id)) or 0
    if existing is not None and existing.position != last_position:
        raise HTTPException(409, "这条问题之后已有新消息，请作为新问题重新发送")
    if existing is None:
        existing = ChatMessage(conversation_id=conversation_id, request_id=request_id, position=last_position + 1,
                               role="user", content=question, status="pending")
        db.add(existing)
    else:
        existing.status = "pending"
        existing.error_message = None
    token = new_id()
    conversation.generation_token = token
    conversation.generating_at = now_utc()
    conversation.updated_at = now_utc()
    if conversation.title == "新对话":
        conversation.title = question[:40]
    lesson_id = conversation.lesson_id
    lesson = db.scalar(select(Lesson).where(Lesson.id == lesson_id))
    course_id = lesson.course_id
    position = existing.position
    context = recent_context(db, conversation_id, position)
    db.commit()
    try:
        options = {"history": context} if context else {}
        result = ask_course(db, course_id, username, question, lesson_id=lesson_id, **options)
        db.rollback()
        conversation = owned_conversation(db, conversation_id, username, lock=True)
        if conversation.generation_token != token:
            raise HTTPException(409, "当前回答已中断，请刷新对话")
        user_message = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
            ChatMessage.request_id == request_id, ChatMessage.role == "user"))
        user_message.status = "completed"
        user_message.error_message = None
        db.add(ChatMessage(conversation_id=conversation_id, request_id=request_id, position=position + 1,
            role="assistant", content=result["answer"], citations_json=json.dumps(result["citations"], ensure_ascii=False)))
        conversation.generation_token = None
        conversation.generating_at = None
        conversation.updated_at = now_utc()
        db.commit()
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "回答失败，请稍后重试"
        _finish_failed(db, conversation_id, request_id, token, detail)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, detail) from exc
    return read_messages(db, conversation_id, username)

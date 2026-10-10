"""按请求编号停止生成，避免旧页面停止后来发起的新问题。"""
from fastapi import HTTPException
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import ChatMessage, now_utc
from .access import owned_conversation
from .messages import read_messages


def stop_generation(db: Session, conversation_id: str, username: str, request_id: str) -> dict:
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    question = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.request_id == request_id, ChatMessage.role == "user"))
    if question is None:
        raise HTTPException(409, "问题尚未开始生成，请稍后再试")
    if question.status != "pending":
        db.commit()
        return read_messages(db, conversation_id, username)
    question.status = "cancelled"
    question.error_message = "已停止生成"
    if conversation.generation_preview_json:
        preview = json.loads(conversation.generation_preview_json)
        db.add(ChatMessage(conversation_id=conversation_id, request_id=request_id, position=question.position + 1,
            role="assistant", content=preview["answer"], citations_json=json.dumps(preview["citations"], ensure_ascii=False),
            status="cancelled", error_message="已停止生成，回答未完成"))
    conversation.generation_preview_json = None
    conversation.generation_token = None
    conversation.generating_at = None
    conversation.updated_at = now_utc()
    db.commit()
    return read_messages(db, conversation_id, username)

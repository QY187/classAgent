import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import ChatMessage
from .access import owned_conversation
from .conversations import conversation_read


def message_read(item: ChatMessage) -> dict:
    return {"id": item.id, "request_id": item.request_id, "position": item.position, "role": item.role,
            "content": item.content, "status": item.status, "citations": json.loads(item.citations_json),
            "error_message": item.error_message, "created_at": item.created_at}


def read_messages(db: Session, conversation_id: str, username: str) -> dict:
    conversation = owned_conversation(db, conversation_id, username)
    items = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.position))
    return {"conversation": conversation_read(conversation), "messages": [message_read(item) for item in items]}

from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import ChatMessage


def recent_context(db: Session, conversation_id: str, before_position: int) -> list[dict]:
    items = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.position < before_position, ChatMessage.status == "completed"
    ).order_by(ChatMessage.position.desc()).limit(8)))
    return [{"role": item.role, "content": item.content[:1200]} for item in reversed(items)]

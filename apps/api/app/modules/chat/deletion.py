from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session
from ...shared.models import ChatConversation
from .access import owned_conversation
from .generation import is_generating


def delete_conversation(db: Session, identity: str, username: str) -> None:
    item = owned_conversation(db, identity, username, lock=True)
    if is_generating(item):
        raise HTTPException(409, "请等待回答完成后删除对话")
    db.execute(delete(ChatConversation.__table__).where(ChatConversation.__table__.c.id == identity))
    db.commit(); db.expunge_all()

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from uuid import UUID
from ...core.db import get_db
from ...core.deps import get_current_user
from . import conversations, messages
from .sending import send_message

router = APIRouter(prefix="/chat", tags=["chat"])


class SendMessage(BaseModel):
    content: str = Field(min_length=2, max_length=1000)
    request_id: UUID


@router.post("/conversations/{conversation_id}/ask")
def send(conversation_id: str, body: SendMessage, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return send_message(db, conversation_id, username, body.content, str(body.request_id))


@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return messages.read_messages(db, conversation_id, username)


@router.get("/lessons/{lesson_id}/conversations")
def list_conversations(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.list_conversations(db, lesson_id, username)


@router.post("/lessons/{lesson_id}/conversations", status_code=201)
def create_conversation(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.create_conversation(db, lesson_id, username)

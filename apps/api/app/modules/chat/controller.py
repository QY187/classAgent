from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from uuid import UUID
from fastapi.responses import StreamingResponse
from .access import owned_conversation
from .streaming import message_events
from .cancellation import stop_generation
from ...core.db import get_db
from ...core.deps import get_current_user
from . import conversations, messages
from .sending import send_message
from .tree import lesson_tree
from .deletion import delete_conversation
from .search import search_conversations

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/conversations", status_code=201)
def create_global_conversation(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.create_global_conversation(db, username)


@router.get("/conversations")
def list_global_conversations(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.list_global_conversations(db, username)


@router.post("/courses/{course_id}/conversations", status_code=201)
def create_course_conversation(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.create_course_conversation(db, course_id, username)


@router.get("/courses/{course_id}/conversations")
def list_course_conversations(course_id: str, include_lessons: bool = False, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.list_course_conversations(db, course_id, username, include_lessons=include_lessons)


@router.get("/search")
def search(query: str = Query(min_length=1, max_length=200), username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return search_conversations(db, username, query)


@router.delete("/conversations/{conversation_id}", status_code=204)
def remove(conversation_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_conversation(db, conversation_id, username)


@router.get("/lessons")
def get_lesson_tree(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return lesson_tree(db, username)


class SendMessage(BaseModel):
    content: str = Field(min_length=2, max_length=1000)
    request_id: UUID


class RenameConversation(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class StopGeneration(BaseModel):
    request_id: UUID


@router.post("/conversations/{conversation_id}/stop")
def stop(conversation_id: str, body: StopGeneration, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return stop_generation(db, conversation_id, username, str(body.request_id))


@router.patch("/conversations/{conversation_id}")
def rename(conversation_id: str, body: RenameConversation, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.rename_conversation(db, conversation_id, username, body.title)


@router.post("/conversations/{conversation_id}/ask")
def send(conversation_id: str, body: SendMessage, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return send_message(db, conversation_id, username, body.content, str(body.request_id))


@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return messages.read_messages(db, conversation_id, username)


@router.post("/conversations/{conversation_id}/ask/stream")
def send_stream(conversation_id: str, body: SendMessage, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_conversation(db, conversation_id, username)
    db.rollback()
    return StreamingResponse(message_events(conversation_id, username, body.content, str(body.request_id)),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/lessons/{lesson_id}/conversations")
def list_conversations(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.list_conversations(db, lesson_id, username)


@router.post("/lessons/{lesson_id}/conversations", status_code=201)
def create_conversation(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return conversations.create_conversation(db, lesson_id, username)

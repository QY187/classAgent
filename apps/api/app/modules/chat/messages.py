import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import ChatMessage, Quiz
from .quiz_actions import quiz_card
from .access import owned_conversation
from .conversations import conversation_read


def message_read(item: ChatMessage) -> dict:
    return {"id": item.id, "request_id": item.request_id, "position": item.position, "role": item.role,
            "content": item.content, "status": item.status, "citations": json.loads(item.citations_json),
            "error_message": item.error_message, "created_at": item.created_at,
            "steps": json.loads(item.agent_steps_json)}


def read_messages(db: Session, conversation_id: str, username: str) -> dict:
    conversation = owned_conversation(db, conversation_id, username)
    items = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.position)))
    quizzes = db.scalars(select(Quiz).where(Quiz.agent_request_key.in_([item.id for item in items if item.role == "user"])))
    artifacts = {quiz.agent_request_key: quiz_card(db, quiz) for quiz in quizzes}
    return {"conversation": conversation_read(conversation), "messages": [{**message_read(item), "artifacts": [artifacts[item.id]] if item.id in artifacts else []} for item in items]}

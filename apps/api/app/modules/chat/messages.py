import json
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import ChatMessage, Quiz, AgentAction, Course, Lesson
from .course_actions import visible_action
from .lesson_actions import visible_action as visible_lesson_action
from .knowledge_actions import visible_action as visible_knowledge_action
from .retry_actions import visible_action as visible_retry_action
from .edit_actions import visible_action as visible_edit_action
from .quiz_actions import quiz_card
from .access import owned_conversation
from .conversations import conversation_read


def enrich_citations(db, citations, user_id):
    """只补充当前用户可见的课程信息，不把历史来源误指向其他课程。"""
    lesson_ids = {item.get("lesson_id") for item in citations if item.get("lesson_id")}
    course_ids = {item.get("course_id") for item in citations if item.get("course_id")}
    lessons = dict(db.execute(select(Lesson.id, Course.name).join(Course, Lesson.course_id == Course.id)
        .where(Lesson.id.in_(lesson_ids), Course.owner_id == user_id)).all()) if lesson_ids else {}
    courses = dict(db.execute(select(Course.id, Course.name).where(Course.id.in_(course_ids),
        Course.owner_id == user_id)).all()) if course_ids else {}
    for item in citations:
        name = courses.get(item.get("course_id")) or lessons.get(item.get("lesson_id"))
        if name:
            item["course_name"] = name
        if item.get("source_type", "transcript") == "transcript" and item.get("lesson_id") not in lessons:
            item["source_status"] = "unavailable"
    return citations


def message_read(item: ChatMessage) -> dict:
    return {"id": item.id, "request_id": item.request_id, "position": item.position, "role": item.role,
            "content": item.content, "status": item.status, "citations": json.loads(item.citations_json),
            "error_message": item.error_message, "created_at": item.created_at,
            "model": json.loads(item.agent_model_json) if item.agent_model_json else None,
            "steps": json.loads(item.agent_steps_json)}


def read_messages(db: Session, conversation_id: str, username: str) -> dict:
    from ..materials.content import refresh_material_citation
    conversation = owned_conversation(db, conversation_id, username)
    items = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.position)))
    from ...shared.models import ChatMemoryUse
    from ..memory.settings import effective_settings
    memory_entries=defaultdict(list)
    try:
        with db.begin_nested():
            memory_policy=effective_settings(db,conversation.user_id,conversation_id)
            for entry in db.scalars(select(ChatMemoryUse).where(ChatMemoryUse.message_id.in_([item.id for item in items]))):
                memory_entries[entry.message_id].append(entry)
    except Exception:
        memory_policy={"history_enabled":False,"long_term_enabled":False}
    quizzes = db.scalars(select(Quiz).where(Quiz.agent_request_key.in_([item.id for item in items if item.role == "user"])))
    artifacts = {quiz.agent_request_key: quiz_card(db, quiz) for quiz in quizzes}
    action_artifacts = {}
    for receipt in db.scalars(select(AgentAction).where(AgentAction.message_id.in_([item.id for item in items if item.role == "user"])).order_by(AgentAction.created_at, AgentAction.id)):
        reader = {"create_course": visible_action, "create_lesson": visible_lesson_action,
                  "update_knowledge_status": visible_knowledge_action, "retry_transcription": visible_retry_action,
                  "update_course":visible_edit_action, "update_lesson":visible_edit_action}.get(receipt.tool)
        result = reader(db, json.loads(receipt.result_json), username) if reader else None
        if result:
            action_artifacts.setdefault(receipt.message_id, []).append(result)
    messages = []
    for item in items:
        message = message_read(item)
        message["citations"] = [refresh_material_citation(db, citation, username) for citation in message["citations"]]
        message["artifacts"] = ([artifacts[item.id]] if item.id in artifacts else []) + action_artifacts.get(item.id, [])
        from ..memory.usage import read_usage
        message["memory_sources"] = read_usage(db,item.id,conversation.user_id,conversation_id,entries=memory_entries[item.id],policy=memory_policy) if item.role=="assistant" else []
        messages.append(message)
    enrich_citations(db, [citation for message in messages for citation in message["citations"]], conversation.user_id)
    return {"conversation": conversation_read(conversation), "messages": messages}

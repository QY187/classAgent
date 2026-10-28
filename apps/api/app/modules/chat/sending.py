"""消息发送、幂等请求和失败恢复；按对话范围绑定 Agent 或历史课次检索。"""
import json
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from ...shared.models import ChatConversation, ChatMessage, Lesson, new_id, now_utc
from ..rag.service import ask_course
from ..agent.loop import run_agent
from ..agent.tools import ToolContext
from .access import owned_conversation, owned_course
from .messages import read_messages
from .generation import is_generating, GenerationStopped
from .context import recent_context
from .previews import save_preview
from .agent_progress import save_agent_step
from .quiz_actions import resolve_quiz_intent, generate_for_message
from .write_intents import resolve_write_intents
from .course_actions import actions_for_message, action_hint as course_action_hint
from .edit_actions import actions_for_message as edit_actions, action_hint as edit_action_hint
from .retry_actions import actions_for_message as retry_actions
from .intents import request_text
from .lesson_actions import actions_for_message as lesson_actions, action_hint as lesson_action_hint
from .knowledge_actions import actions_for_message as knowledge_actions, status_verification_hint


def _finish_failed(db: Session, conversation_id: str, request_id: str, token: str, error: str):
    db.rollback()
    conversations = ChatConversation.__table__
    updated = db.execute(update(conversations).where(conversations.c.id == conversation_id,
        conversations.c.generation_token == token).values(generation_token=None, generating_at=None, generation_preview_json=None))
    if updated.rowcount:
        messages = ChatMessage.__table__
        db.execute(update(messages).where(messages.c.conversation_id == conversation_id,
            messages.c.request_id == request_id, messages.c.role == "user", messages.c.status == "pending"
        ).values(status="failed", error_message=error))
    db.commit()


def send_message(db: Session, conversation_id: str, username: str, content: str, request_id: str, *, on_progress=None, on_started=None, on_step=None) -> dict:
    question = content.strip()
    if not 2 <= len(question) <= 1000:
        raise HTTPException(422, "请输入 2 到 1000 字的问题")
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    if conversation.is_archived:
        raise HTTPException(409, "请恢复归档对话后再提问")
    existing = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.request_id == request_id, ChatMessage.role == "user"))
    if existing is not None and existing.content != question:
        raise HTTPException(409, "请求编号已用于其他问题")
    if existing is not None and existing.status in ("completed", "cancelled"):
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
        existing.agent_steps_json = "[]"
    token = new_id()
    conversation.generation_token = token
    conversation.generation_preview_json = None
    conversation.generating_at = now_utc()
    conversation.updated_at = now_utc()
    if conversation.title == "新对话":
        conversation.title = question[:40]
    lesson_id = conversation.lesson_id
    course_id = conversation.course_id
    if lesson_id is not None:
        lesson = db.scalar(select(Lesson).where(Lesson.id == lesson_id))
        course_id = lesson.course_id
    position = existing.position
    context = recent_context(db, conversation_id, position)
    db.commit()
    question_id = existing.id
    try:
        if on_started is not None:
            on_started()
        def check():
            db.rollback()
            current = owned_conversation(db, conversation_id, username)
            if current.generation_token != token:
                raise GenerationStopped()
        options = {"history": context} if context else {}
        if on_progress is not None:
            def publish(result):
                check()
                save_preview(db, conversation_id, username, token, result)
                on_progress(result)
            options["on_progress"] = publish
            options["on_check"] = check
        check()
        if lesson_id is None:
            def publish_step(raw):
                progress = save_agent_step(db, conversation_id, username, request_id, token, raw)
                if on_step is not None:
                    on_step(progress)
            quiz_intent = resolve_quiz_intent(question, context)
            check()
            bound_course = owned_course(db, course_id, username).name if course_id else None
            db.rollback()  # 模型理解期间不持有数据库事务。
            semantic = resolve_write_intents(question, context, bound_course=bound_course)
            check()
            generate = (lambda args: generate_for_message(db, conversation_id, username, question_id, token, args)) if quiz_intent != "none" else None
            result = run_agent(db, ToolContext(username, course_id=course_id, generate_quiz=generate,
                practice_only=quiz_intent == "practice",
                actions=actions_for_message(db, conversation_id, username, question_id, token, question, context, semantic) |
                        lesson_actions(db, conversation_id, username, question_id, token, question, context, semantic) |
                        knowledge_actions(db, conversation_id, username, question_id, token, question, context, semantic) |
                        retry_actions(db, conversation_id, username, question_id, token, question, context) |
                        edit_actions(db, conversation_id, username, question_id, token, question, context, semantic),
                action_hints={"create_course": course_action_hint(question, context, semantic), "create_lesson": lesson_action_hint(question, context, semantic),
                    "update_knowledge_status": semantic.get("knowledge"),
                    "write_request_issue":semantic.get("issue", ""),
                    "verify_knowledge_status":status_verification_hint(db, username, course_id, question, context),
                    "update_course":edit_action_hint(question, context, semantic), "update_lesson":edit_action_hint(question, context, semantic)}), request_text(question), history=context, on_check=check, on_step=publish_step)
            if on_progress is not None:
                publish(result)
        else:
            result = ask_course(db, course_id, username, question, lesson_id=lesson_id, **options)
        db.rollback()
        conversation = owned_conversation(db, conversation_id, username, lock=True)
        if conversation.generation_token != token:
            raise GenerationStopped()
        user_message = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
            ChatMessage.request_id == request_id, ChatMessage.role == "user"))
        user_message.status = "completed"
        user_message.error_message = None
        db.add(ChatMessage(conversation_id=conversation_id, request_id=request_id, position=position + 1,
            role="assistant", content=result["answer"], citations_json=json.dumps(result["citations"], ensure_ascii=False)))
        conversation.generation_token = None
        conversation.generation_preview_json = None
        conversation.generating_at = None
        conversation.updated_at = now_utc()
        db.commit()
    except GenerationStopped:
        db.rollback()
        return read_messages(db, conversation_id, username)
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "回答失败，请稍后重试"
        _finish_failed(db, conversation_id, request_id, token, detail)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, detail) from exc
    return read_messages(db, conversation_id, username)

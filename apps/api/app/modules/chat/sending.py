"""消息发送、幂等请求和失败恢复；所有对话按后端范围绑定 Agent。"""
import json
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from ...core.telemetry import bind_request, request_trace, span, trace_event, traced
from ...core.chat_failures import ChatRequestFailure, public_failure
from ...core.model_budget import user_budget
from ...shared.models import ChatConversation, ChatMessage, Lesson, new_id, now_utc
from ..agent.loop import run_agent
from ..agent.tools import ToolContext
from ..agent.synthesis import synthesize_result
from .access import owned_conversation, owned_course, owned_lesson
from .messages import read_messages
from .generation import is_generating, GenerationStopped
from .context import recent_context
from .previews import save_preview
from .agent_progress import save_agent_step
from .quiz_actions import generate_for_message
from .turn_intents import resolve_turn_intent
from .intent_schema import TurnDecision
from .pending_tasks import start_request, save_decision, next_pending, valid_pending, MAX_CLARIFICATIONS
from .intent_entities import intent_entities
from .course_actions import actions_for_message, action_hint as course_action_hint
from .edit_actions import actions_for_message as edit_actions, action_hint as edit_action_hint
from .retry_actions import actions_for_message as retry_actions
from .lesson_actions import actions_for_message as lesson_actions, action_hint as lesson_action_hint
from .knowledge_actions import actions_for_message as knowledge_actions
from .action_verification import verify_actions


@traced("request.fail_persist")
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


@user_budget
def send_message(db: Session, conversation_id: str, username: str, content: str, request_id: str, *, on_progress=None, on_started=None, on_step=None) -> dict:
    with request_trace(request_id, conversation_id):
        try:
            return _send_message(db, conversation_id, username, content, request_id,
                                 on_progress=on_progress, on_started=on_started, on_step=on_step)
        except ChatRequestFailure:
            raise
        except Exception as exc:
            if isinstance(exc, HTTPException) and exc.status_code < 500:
                raise
            failure = public_failure(exc, stage="preparing")
            bind_request(error_code=failure.code)
            raise ChatRequestFailure(failure) from exc


def _send_message(db: Session, conversation_id: str, username: str, content: str, request_id: str, *, on_progress=None, on_started=None, on_step=None) -> dict:
    question = content.strip()
    if not 2 <= len(question) <= 1000:
        raise HTTPException(422, "请输入 2 到 1000 字的问题")
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    bind_request(user_id=conversation.user_id, course_id=conversation.course_id, lesson_id=conversation.lesson_id)
    if conversation.is_archived:
        raise HTTPException(409, "请恢复归档对话后再提问")
    existing = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.request_id == request_id, ChatMessage.role == "user"))
    if existing is not None and existing.content != question:
        raise HTTPException(409, "请求编号已用于其他问题")
    if existing is not None and existing.status in ("completed", "cancelled"):
        bind_request(cached=True, outcome="cancelled" if existing.status == "cancelled" else "replayed")
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
        bind_request(retry=False, cached=False)
        existing = ChatMessage(conversation_id=conversation_id, request_id=request_id, position=last_position + 1,
                               role="user", content=question, status="pending")
        db.add(existing)
    else:
        bind_request(retry=True, cached=False)
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
    intent_snapshot = start_request(existing, conversation)
    db.commit()
    question_id = existing.id
    bind_request(message_id=question_id)
    failure_stage = "context"
    try:
        if on_started is not None:
            on_started()
        def check():
            db.rollback()
            current = owned_conversation(db, conversation_id, username)
            if current.generation_token != token:
                raise GenerationStopped()
        if on_progress is not None:
            def publish(result):
                check()
                save_preview(db, conversation_id, username, token, result)
                on_progress(result)
        check()
        def publish_step(raw):
            progress = save_agent_step(db, conversation_id, username, request_id, token, raw)
            if on_step is not None:
                on_step(progress)
        with span("intent.context"):
            bound_course = owned_course(db, course_id, username).name if course_id else None
            bound_lesson = owned_lesson(db, lesson_id, username).title if lesson_id else None
            pending = valid_pending(intent_snapshot.get("pending"), conversation, position)
            entities = intent_entities(db, conversation.user_id, course_id, lesson_id)
        db.rollback()  # 模型理解期间不持有数据库事务。
        # 每条消息都做语义规划；只从后端待办续接，普通历史不能恢复写权限。
        # 同请求失败重试复用已验证计划，不因模型重判而改变动作或参数。
        failure_stage = "planning"
        with span("intent.plan", cached=bool(intent_snapshot.get("decision")), pending=bool(pending)) as planning:
            if intent_snapshot.get("decision"):
                decision = TurnDecision.model_validate(intent_snapshot["decision"])
            else:
                intent_snapshot["pending"] = pending
                decision = resolve_turn_intent(question, context, pending=pending,
                    bound_course=bound_course, bound_lesson=bound_lesson, entities=entities)
            planning.set(relation=decision.relation)
        if not intent_snapshot.get("decision"):
            check()
            current = owned_conversation(db, conversation_id, username, lock=True)
            if current.generation_token != token:
                raise GenerationStopped()
            save_decision(db.get(ChatMessage, question_id), intent_snapshot, decision)
            db.commit()
        semantic = decision.intent.legacy()
        failure_stage = "tools"
        check()
        quiz_intent = semantic.get("quiz", "none") if semantic else "none"
        generate = (lambda args: generate_for_message(db, conversation_id, username, question_id, token, args,
            requested=semantic.get("quiz_spec"))) if quiz_intent != "none" else None
        verification = verify_actions(db, conversation_id, username, question_id, semantic["verify"]) if semantic and "verify" in semantic else None
        action_hints = {"create_course": course_action_hint(question, context, semantic),
                        "create_lesson": lesson_action_hint(question, context, semantic),
                        "update_knowledge_status": semantic.get("knowledge") if semantic else None,
                        "write_request_issue": semantic.get("issue", "") if semantic else "",
                        "update_course": edit_action_hint(question, context, semantic),
                        "update_lesson": edit_action_hint(question, context, semantic)}
        if semantic is not None:
            if decision.intent.outputs is not None:
                action_hints["response_contract"] = {"goal": decision.intent.goal, "outputs": decision.intent.outputs,
                    "requirements": [item.model_dump() for item in decision.intent.requirements]}
            action_hints.update({"semantic_queries": semantic.get("queries", []),
                                 "answer_mode": semantic.get("answer_mode", "standard"),
                                 "semantic_catalog": semantic.get("catalog", []),
                                 "retry_transcription": semantic.get("retry", {}),
                                 "quiz_request": semantic.get("quiz_spec", {})})
        if decision.relation == "continue":
            action_hints["pending_task"] = {"request": intent_snapshot["pending"]["request"],
                "clarification": intent_snapshot["pending"]["clarification"],
                "instruction": "用户本轮在补充已授权待办，按本轮语义参数执行剩余任务；已完成动作不重放。"}
        agent_context = ToolContext(username, course_id=course_id, lesson_id=lesson_id, generate_quiz=generate,
            practice_only=quiz_intent == "practice",
            actions=actions_for_message(db, conversation_id, username, question_id, token, question, context, semantic) |
                    lesson_actions(db, conversation_id, username, question_id, token, question, context, semantic) |
                    knowledge_actions(db, conversation_id, username, question_id, token, question, context, semantic) |
                    retry_actions(db, conversation_id, username, question_id, token, question, context, semantic) |
                    edit_actions(db, conversation_id, username, question_id, token, question, context, semantic),
            action_hints=action_hints)
        verification_only = verification and set(semantic) <= {"verify", "queries", "catalog"} and not semantic.get("queries")
        clarification = decision.clarification or decision.intent.issue
        if clarification:
            result = {"answer": clarification, "citations": [], "outcome": "needs_input", "steps": []}
        elif decision.relation == "cancel" and not decision.intent.queries:
            result = {"answer": "已取消待处理的操作。" if intent_snapshot.get("pending") else "本轮不执行任何操作。",
                      "citations": [], "outcome": "answered", "steps": []}
        elif verification_only:
            result = {"answer": verification, "citations": [], "outcome": "answered", "steps": []}
        else:
            failure_stage = "execution"
            def summarize_verified(read_result, refresh):
                nonlocal failure_stage
                failure_stage = "answer"
                summarized = synthesize_result(question, read_result, on_check=check)
                check()
                current = refresh()
                if (current.get("answer_materials") != read_result.get("answer_materials")
                        or current.get("citations") != read_result.get("citations")):
                    raise ChatRequestFailure("answer_sources_changed")
                return summarized

            result = run_agent(db, agent_context, question, history=context, on_check=check, on_step=publish_step,
                on_answer=summarize_verified if decision.intent.outputs is not None else None)
        failure_stage = "answer"
        # 只发布模型组织的回答和公开引用，内部证据包不进入预览或消息接口。
        result.pop("answer_materials", None)
        if verification and not verification_only:
            result["answer"] = verification + "\n\n" + result["answer"]
        bind_request(outcome=result.get("outcome", "answered"), citation_count=len(result.get("citations", [])))
        if (decision.relation == "continue" and intent_snapshot["pending"]["turns"] >= MAX_CLARIFICATIONS
                and (result.get("outcome") == "needs_input" or result.get("clarification"))):
            result["answer"] += "\n\n本次补充次数已达到上限，请重新完整描述操作、目标和参数。"
        if on_progress is not None:
            publish(result)
        failure_stage = "saving"
        with span("request.persist"):
            db.rollback()
            conversation = owned_conversation(db, conversation_id, username, lock=True)
            if conversation.generation_token != token:
                raise GenerationStopped()
            user_message = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
                ChatMessage.request_id == request_id, ChatMessage.role == "user"))
            user_message.status = "completed"
            user_message.error_message = None
            conversation.pending_task_json = next_pending(db, conversation, user_message, intent_snapshot, decision, result)
            db.add(ChatMessage(conversation_id=conversation_id, request_id=request_id, position=position + 1,
                role="assistant", content=result["answer"], citations_json=json.dumps(result["citations"], ensure_ascii=False)))
            conversation.generation_token = None
            conversation.generation_preview_json = None
            conversation.generating_at = None
            conversation.updated_at = now_utc()
            db.commit()
        failure_stage = "history"
        return read_messages(db, conversation_id, username)
    except GenerationStopped:
        bind_request(outcome="cancelled")
        trace_event("request.cancelled", reason="generation_stopped")
        db.rollback()
        return read_messages(db, conversation_id, username)
    except Exception as exc:
        failure = public_failure(exc, stage=failure_stage)
        bind_request(error_code=failure.code)
        try:
            _finish_failed(db, conversation_id, request_id, token, failure.message)
        except Exception as persistence_error:
            # 保存失败原因失败时，仍向前端报告原始分类，避免二次异常掩盖真正原因。
            trace_event("request.failure_record_failed", reason="storage_unavailable", error_type=type(persistence_error).__name__)
        raise ChatRequestFailure(failure) from exc

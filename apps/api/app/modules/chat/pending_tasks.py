"""会话待澄清任务及请求级计划快照；不依赖问号或历史关键词判断状态。"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from ...shared.models import AgentAction, ChatMessage, Quiz, new_id, now_utc
from .intent_schema import IntentPayload, TurnDecision, operation_tools


PENDING_TTL = timedelta(minutes=30)
MAX_CLARIFICATIONS = 4


def _scope(conversation):
    return {"conversation_id": conversation.id, "user_id": conversation.user_id,
            "course_id": conversation.course_id, "lesson_id": conversation.lesson_id}


def valid_pending(raw, conversation, before_position):
    """状态只属于同一用户/会话/范围，且只能承接紧邻的已完成澄清回合。"""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(value, dict) or value.get("version") != 1 or value.get("scope") != _scope(conversation):
            return None
        expiry = datetime.fromisoformat(value["expires_at"])
        if expiry.tzinfo is None or expiry <= now_utc() or value["position"] != before_position - 1:
            return None
        if not isinstance(value.get("turns"), int) or not 1 <= value["turns"] <= MAX_CLARIFICATIONS:
            return None
        IntentPayload.model_validate(value["intent"])
        if not isinstance(value.get("id"), str) or not value["id"]:
            return None
        return value
    except (ValueError, TypeError, KeyError):
        return None


def request_snapshot(message):
    try:
        value = json.loads(message.intent_state_json or "{}")
        if value.get("version") == 1 and value.get("request") == message.content:
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def start_request(message, conversation):
    """在模型调用前保存待办输入；重试复用同一快照，取消/换话题不会遗留活跃旧待办。"""
    snapshot = request_snapshot(message)
    if snapshot is None:
        snapshot = {"version": 1, "request": message.content,
                    "pending": valid_pending(conversation.pending_task_json, conversation, message.position),
                    "decision": None}
        message.intent_state_json = json.dumps(snapshot, ensure_ascii=False)
    conversation.pending_task_json = None
    return snapshot


def save_decision(message, snapshot, decision: TurnDecision):
    snapshot = snapshot | {"decision": decision.model_dump()}
    message.intent_state_json = json.dumps(snapshot, ensure_ascii=False)


def completed_tools(db, message_id):
    tools = set(db.scalars(select(AgentAction.tool).where(AgentAction.message_id == message_id)))
    # 小测实体本身就是幂等回执；旧系统并不为出题写 AgentAction。
    if db.scalar(select(Quiz.id).where(Quiz.agent_request_key == message_id).execution_options(include_deleted=True)):
        tools.update({"generate_quiz", "generate_practice_quiz"})
    return tools


def next_pending(db, conversation, message, snapshot, decision: TurnDecision, result):
    """只保存未完成委托；已成功部分依据数据库回执扣除，不依赖模型声称成功。"""
    if decision.relation == "cancel" or decision.intent.issue:
        return None
    previous = snapshot.get("pending") if decision.relation == "continue" else None
    done = completed_tools(db, message.id) | set((previous or {}).get("completed_tools", []))
    remaining = decision.intent.model_copy(deep=True)
    for key, tool in operation_tools(remaining).items():
        if tool in done:
            setattr(remaining, key, None)
    # 模型/工具失败不自动转成可续接任务；明确请求补参或部分成功且有澄清才保存。
    needs_input = result.get("outcome") == "needs_input" or bool(result.get("clarification"))
    if not needs_input:
        return None
    # 只读澄清可继续；已全部完成的写请求绝不以其旧委托重建待办。
    if decision.intent.write_keys() and not remaining.write_keys():
        return None
    turns = (previous or {}).get("turns", 0) + 1
    if turns > MAX_CLARIFICATIONS:
        return None
    return json.dumps({
        "version": 1, "id": (previous or {}).get("id") or new_id(), "scope": _scope(conversation),
        "position": message.position + 1, "source_message_id": message.id,
        "expires_at": (previous or {}).get("expires_at") or (now_utc() + PENDING_TTL).isoformat(),
        "turns": turns, "intent": remaining.model_dump(exclude_none=True),
        "request": (previous or {}).get("request") or message.content,
        "date_source": decision.date_source or (previous or {}).get("date_source"),
        "clarification": result.get("clarification") or result["answer"],
        "completed_tools": sorted(done),
    }, ensure_ascii=False)

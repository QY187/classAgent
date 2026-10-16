"""用户可见的工具步骤；仅保存状态，不保存模型参数与原始工具结果。"""
import json
from sqlalchemy import select
from .access import owned_conversation
from .generation import GenerationStopped
from ...shared.models import ChatMessage

LABELS = {
    "list_courses": "查询课程",
    "list_lessons": "查询课次",
    "search_course": "搜索课堂内容",
    "get_transcript": "读取课堂原文",
    "get_summary": "读取课堂纪要",
    "generate_quiz": "生成课堂小测",
    "list_knowledge_points": "查询知识点状态",
    "list_wrong_questions": "查询错题本",
    "generate_practice_quiz": "生成薄弱点练习",
}
ERRORS = {
    "unknown_tool": "不支持该操作",
    "invalid_arguments": "查询条件不符合要求",
    "not_found": "资料不存在或当前范围不可访问",
    "unauthenticated": "请重新登录",
    "result_too_large": "读取结果过长，需要缩小范围",
    "generation_failed": "小测生成失败，请查看回答说明",
}


def save_agent_step(db, conversation_id, username, request_id, token, raw):
    db.rollback()
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    if conversation.generation_token != token:
        raise GenerationStopped()
    question = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.request_id == request_id, ChatMessage.role == "user"))
    if question is None or question.status != "pending":
        raise GenerationStopped()
    identity, status = raw.get("id"), raw.get("status")
    if not isinstance(identity, str) or not 1 <= len(identity) <= 128 or status not in {"running", "completed", "failed"}:
        raise ValueError("无效工具进度")
    step = {"id": identity, "label": LABELS.get(raw.get("tool"), "读取工具"), "status": status}
    if status == "failed":
        step["error"] = ERRORS.get(raw.get("error_code"), "读取失败，请稍后重试")
    steps = json.loads(question.agent_steps_json)
    index = next((i for i, item in enumerate(steps) if item["id"] == identity), None)
    if index is None:
        if len(steps) >= 8:
            raise ValueError("工具进度超过限制")
        steps.append(step)
    else:
        steps[index] = step
    question.agent_steps_json = json.dumps(steps, ensure_ascii=False)
    db.commit()
    return {"request_id": request_id, "steps": steps}

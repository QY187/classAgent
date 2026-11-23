import json

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...core.chat_failures import ChatRequestFailure, public_failure
from ...core.telemetry import annotate, span
from .registry import TOOLS
from .tools import ToolContext, check_course, check_lesson


def execute_tool(db: Session, context: ToolContext, name: str, arguments: dict | str) -> dict:
    """执行白名单工具，返回可供后续模型循环和任务记录使用的 JSON 结果。"""
    with span("tool.execute", kind="tool", tool=name if name in TOOLS else "unknown") as execution:
        result = _execute_tool(db, context, name, arguments)
        if not result["ok"]:
            execution.set(error_code=result["error"]["code"])
        data = result.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                execution.set(result_count=len(data["items"]))
            if data.get("retrieval_method"):
                execution.set(retrieval_method=data["retrieval_method"])
        return result


def _execute_tool(db: Session, context: ToolContext, name: str, arguments: dict | str) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        return failure(name, "unknown_tool", "不支持该工具")
    if context.lesson_id is not None and context.course_id is None:
        return failure(name, "invalid_context", "课次范围必须同时绑定所属课程")
    try:
        if isinstance(arguments, str):
            if len(arguments) > 16000:
                return failure(name, "invalid_arguments", "工具参数过长")
            arguments = json.loads(arguments)
        payload = tool.arguments.model_validate(arguments)
    except (ValidationError, ValueError, TypeError) as exc:
        annotate(error_type=type(exc).__name__)
        # 不回传模型输入、异常详情或内部信息。
        return failure(name, "invalid_arguments", "工具参数不符合定义，请检查字段与取值范围")
    try:
        user_id_for_username(db, context.username)
        if context.course_id is not None:
            check_course(db, context, context.course_id)
        if context.lesson_id is not None:
            check_lesson(db, context, context.lesson_id)
        return {"tool": name, "ok": True, "data": tool.handler(db, context, payload),
                "content_trust": "untrusted_classroom_data"}
    except HTTPException as exc:
        if isinstance(exc, ChatRequestFailure) and exc.failure.code.startswith("quota_"):
            raise
        annotate(error_type=type(exc).__name__, http_status=exc.status_code)
        if isinstance(exc, ChatRequestFailure):
            code = "generation_failed" if name in {"generate_quiz", "generate_practice_quiz"} else exc.failure.code
            return failure(name, code, exc.failure.reason)
        if name in context.actions and exc.status_code in {400, 403, 409}:
            return failure(name, "action_rejected", exc.detail if isinstance(exc.detail, str) else "操作未执行，请检查目标")
        if name in {"generate_quiz", "generate_practice_quiz"} and exc.status_code in {400, 409, 502, 503}:
            cause = public_failure(exc)
            message = (cause.reason if cause.code not in {"internal_error", "service_unavailable"} else
                       exc.detail if isinstance(exc.detail, str) else "小测生成失败，请重试")
            return failure(name, "generation_failed", message)
        code = {401:"unauthenticated", 403:"forbidden", 404:"not_found", 400:"invalid_arguments", 422:"invalid_arguments", 409:"state_not_ready"}.get(exc.status_code, "unavailable")
        messages = {"unauthenticated":"请重新登录", "forbidden":"当前资料或操作不在授权范围内", "not_found":"资料不存在或当前范围不可访问",
                    "invalid_arguments":"本次查询参数或范围不符合要求", "state_not_ready":"资料当前状态不满足读取要求，请查看处理详情", "unavailable":"读取资料的服务暂时不可用，请稍后重试"}
        message = exc.detail if code == "state_not_ready" and isinstance(exc.detail, str) else messages[code]
        return failure(name, code, message)
    except Exception as exc:
        annotate(error_type=type(exc).__name__)
        from ..chat.generation import GenerationStopped
        if isinstance(exc, GenerationStopped):
            raise
        reason = public_failure(exc)
        db.rollback()
        return failure(name, reason.code if reason.code != "internal_error" else "execution_failed", reason.reason)


def failure(name: str, code: str, message: str) -> dict:
    return {"tool": name, "ok": False, "error": {"code": code, "message": message}}

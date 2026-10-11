import json

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from .registry import TOOLS
from .tools import ToolContext, check_course, check_lesson


def execute_tool(db: Session, context: ToolContext, name: str, arguments: dict | str) -> dict:
    """执行白名单工具，返回可供后续模型循环和任务记录使用的 JSON 结果。"""
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
    except (ValidationError, ValueError, TypeError):
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
        code = "unauthenticated" if exc.status_code == 401 else "not_found" if exc.status_code == 404 else "unavailable"
        return failure(name, code, "请重新登录" if code == "unauthenticated" else "资料不存在或当前范围不可访问" if code == "not_found" else "工具暂不可用")
    except Exception:
        return failure(name, "execution_failed", "工具执行失败，请稍后重试")


def failure(name: str, code: str, message: str) -> dict:
    return {"tool": name, "ok": False, "error": {"code": code, "message": message}}

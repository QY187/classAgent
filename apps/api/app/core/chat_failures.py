"""面向用户的失败分类；只使用类型、状态码及明确的业务错误码，不透传异常原文。"""
from dataclasses import dataclass, replace

from fastapi import HTTPException
import httpx
from sqlalchemy.exc import SQLAlchemyError


REASONS = {
    "quota_exhausted": (429, "今日大模型 Token 剩余额度不足以完成本次调用，请减少上下文，或等待北京时间零点额度重置；也可联系管理员调整额度。"),
    "quota_identity_required": (503, "无法确认本次模型调用的用户归属，已停止调用，请联系管理员。"),
    "quota_storage_unavailable": (503, "暂时无法核对 Token 额度，已停止新的模型调用，请稍后重试。"),
    "ai_not_configured": (503, "尚未配置 AI 服务，请联系管理员完成配置。"),
    "model_timeout": (504, "AI 服务未在规定时间内响应，请稍后重试。"),
    "model_connection": (502, "服务器暂时无法连接 AI 服务，请稍后重试。"),
    "model_authentication": (503, "AI 服务认证失败，请联系管理员检查服务凭证。"),
    "model_permission": (503, "AI 服务拒绝访问，请联系管理员检查模型使用权限。"),
    "model_billing": (503, "AI 服务的计费或额度受限，请联系管理员核对。"),
    "model_rate_limited": (503, "AI 服务触发请求限制，请稍后重试；持续出现时请联系管理员。"),
    "model_unavailable": (502, "AI 服务暂时不可用，请稍后重试。"),
    "model_request_rejected": (502, "AI 服务未接受本次模型请求，请联系管理员检查服务配置。"),
    "invalid_model_response": (502, "AI 服务返回的结果不完整或格式不符合要求，请重试。"),
    "intent_timeout": (504, "理解问题超出本次等待时间，请重试或简化问题。"),
    "invalid_intent": (502, "模型未能可靠解析你的需求，请补充目标和要求后重试。"),
    "execution_timeout": (504, "任务执行超出本次时间上限，请拆分需求后重试。"),
    "tool_call_limit": (502, "工具调用次数达到本次上限，请拆分问题后重试。"),
    "round_limit": (502, "任务未在允许的执行轮次内完成，请拆分问题后重试。"),
    "invalid_tool_call": (502, "模型返回的工具调用格式不符合要求，请重试。"),
    "invalid_answer": (502, "生成的回答未通过结果校验，请重试或缩小问题范围。"),
    "answer_sources_changed": (409, "整理回答期间课堂资料或学习记录发生变化，请重新提问以获取最新结果。"),
    "storage_unavailable": (503, "读取或保存对话数据失败，请稍后刷新核对结果。"),
    "request_timeout": (504, "本次请求等待超时，请稍后重试。"),
    "service_unavailable": (503, "处理请求所需的服务暂时不可用，请稍后重试。"),
    "internal_error": (500, "处理过程发生内部异常，暂时无法确认更具体的原因。请重试，或将请求编号提供给管理员。"),
}
STAGES = {
    "preparing": "准备请求", "context": "读取对话上下文", "planning": "理解问题",
    "tools": "准备执行任务", "execution": "执行任务", "answer": "整理回答", "saving": "保存回答", "history": "读取回答记录",
}


@dataclass(frozen=True)
class PublicFailure:
    code: str
    reason: str
    status_code: int
    stage: str | None = None

    @property
    def message(self):
        label = STAGES.get(self.stage)
        return f"{label}阶段失败：{self.reason}" if label else self.reason


class ChatRequestFailure(HTTPException):
    def __init__(self, failure: PublicFailure | str):
        if isinstance(failure, str):
            status, reason = REASONS[failure]
            failure = PublicFailure(failure, reason, status)
        self.failure = failure
        super().__init__(failure.status_code, failure.message)


def public_failure(exc: Exception, *, stage=None) -> PublicFailure:
    if isinstance(exc, ChatRequestFailure):
        return replace(exc.failure, stage=stage or exc.failure.stage)
    chain = []
    current = exc
    while current is not None and len(chain) < 8 and all(current is not item for item in chain):
        chain.append(current)
        current = current.__cause__
    code = None
    for item in chain:
        if isinstance(item, httpx.HTTPStatusError):
            status = item.response.status_code
            code = {401: "model_authentication", 402: "model_billing", 403: "model_permission",
                    408: "model_timeout", 429: "model_rate_limited", 504: "model_timeout"}.get(
                        status, "model_unavailable" if status >= 500 else "model_request_rejected")
            break
        if isinstance(item, (httpx.TimeoutException, TimeoutError)):
            code = "model_timeout" if stage in {"planning", "execution"} or isinstance(item, httpx.TimeoutException) else "request_timeout"
            break
        if isinstance(item, httpx.TransportError):
            code = "model_connection"
            break
        if isinstance(item, SQLAlchemyError):
            code = "storage_unavailable"
            break
    if code is None and isinstance(exc, HTTPException):
        if 400 <= exc.status_code < 500:
            # 业务层主动拒绝请求时使用现有的用户提示；不用于供应商响应正文。
            detail = exc.detail if isinstance(exc.detail, str) else "请求未被接受，请检查输入或重新登录。"
            return PublicFailure("request_rejected", detail, exc.status_code, stage)
        code = {504: "request_timeout", 503: "service_unavailable"}.get(exc.status_code, "internal_error")
    code = code or "internal_error"
    status, reason = REASONS[code]
    return PublicFailure(code, reason, exc.status_code if isinstance(exc, HTTPException) else status, stage)

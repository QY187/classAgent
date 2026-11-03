"""大模型调用预算：后端绑定归属、独立事务预留、按供应商用量结算。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from inspect import signature
import json
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .chat_failures import ChatRequestFailure

_principal = ContextVar("model_budget_principal", default=None)
REJECTED_STATUSES = {400, 401, 402, 403, 404, 405, 413, 415, 422, 429}


@contextmanager
def quota_user(db, user_id):
    # 不复用业务事务：生成结果回滚不应退还已消耗的模型用量。
    token = _principal.set((user_id, sessionmaker(bind=db.get_bind(), expire_on_commit=False)))
    try:
        yield
    finally:
        _principal.reset(token)


def user_budget(function):
    """只装饰接收后端已认证 username、db 的业务入口，不把身份交给模型。"""
    parameters = signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        if not get_settings().token_quota_enabled:
            return function(*args, **kwargs)
        arguments = parameters.bind(*args, **kwargs).arguments
        db, username = arguments["db"], arguments["username"]
        from ..shared.models import User
        user_id = db.scalar(select(User.id).where(User.username == username))
        if user_id is None:
            raise ChatRequestFailure("quota_identity_required")
        with quota_user(db, user_id):
            return function(*args, **kwargs)
    return wrapped


def input_reservation(body):
    """保守输入预算：UTF-8 字节数及协议余量；不是对实际 Token 的伪造估算。"""
    messages, tools = body.get("messages", []), body.get("tools", [])
    serialized = json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)
    return len(serialized.encode("utf-8")) + 256 * (len(messages) + len(tools) + 1)


@dataclass
class ModelReservation:
    sessions: object
    entry_id: str
    sent: bool = False
    finished: bool = False

    def settle(self, actual, *, input_tokens=None, output_tokens=None):
        from ..modules.quotas import service
        try:
            service.settle(self.sessions, self.entry_id, actual, input_tokens=input_tokens, output_tokens=output_tokens)
        except SQLAlchemyError as exc:
            raise ChatRequestFailure("quota_storage_unavailable") from exc
        self.finished = True

    def usage(self, usage):
        if not isinstance(usage, dict):
            return
        valid = lambda value: type(value) is int and value >= 0
        incoming, outgoing = usage.get("prompt_tokens"), usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if valid(incoming) and valid(outgoing):
            # 供应商返回矛盾字段时按较大值记录，不少计已知消耗。
            total = max(total if valid(total) else 0, incoming + outgoing)
        elif valid(total) and any(valid(value) and value > total for value in (incoming, outgoing)):
            # 总量比某个已知分量还小且另一分量缺失，不能声称已知实际总量。
            return
        if valid(total):
            self.settle(total, input_tokens=incoming if valid(incoming) else None,
                        output_tokens=outgoing if valid(outgoing) else None)


@contextmanager
def model_reservation(body, *, purpose):
    if not get_settings().token_quota_enabled:
        yield None
        return
    principal = _principal.get()
    if principal is None:
        raise ChatRequestFailure("quota_identity_required")
    user_id, sessions = principal
    from ..modules.quotas import service
    output = body.get("max_tokens", 4000)
    if type(output) is not int or not 1 <= output <= 32000:
        raise ChatRequestFailure("invalid_model_response")
    try:
        entry_id = service.reserve(sessions, user_id, input_reservation(body) + output,
                                   model=str(body.get("model", "unknown")), purpose=purpose)
    except SQLAlchemyError as exc:
        raise ChatRequestFailure("quota_storage_unavailable") from exc
    reservation = ModelReservation(sessions, entry_id)
    try:
        yield reservation
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        reservation.sent = False
        raise
    finally:
        if not reservation.finished:
            try:
                if reservation.sent:
                    service.uncertain(sessions, entry_id)
                else:
                    reservation.settle(0)
            except Exception:
                # 已写入的预留不自动释放；后续调用仍受限，管理员可核对。
                logging.getLogger("classagent.quotas").warning("quota_settlement_pending")


def quota_chat_post(post, url, *, headers, json, timeout, purpose="chat"):
    with model_reservation(json, purpose=purpose) as reservation:
        body = {**json, "max_tokens": json.get("max_tokens", 4000)} if reservation else json
        if reservation:
            reservation.sent = True
        response = post(url, headers=headers, json=body, timeout=timeout)
        if reservation:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                reservation.usage(payload.get("usage"))
            if not reservation.finished and response.status_code in REJECTED_STATUSES:
                reservation.settle(0)
        return response

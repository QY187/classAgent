"""请求级 JSON 追踪；只记录运行指标，不记录业务正文、SQL 或异常文本。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import json
import logging
import re
from time import perf_counter
from uuid import uuid4


LOGGER = logging.getLogger("classagent.trace")
_trace = ContextVar("agent_trace", default=None)
_spans = ContextVar("agent_spans", default=())
_sink = None
MAX_TRACE_EVENTS = 512
_ATTRIBUTES = {
    "user_id", "course_id", "lesson_id", "message_id", "outcome", "cached", "retry", "tool_call_id",
    "provider", "model", "purpose", "prompt_revision", "tool", "round", "attempt",
    "reason", "error_type", "cause_type", "error_code", "http_status", "result_count", "citation_count",
    "variant_count", "candidate_limit", "vector_count", "lexical_count", "fused_count",
    "rerank_count", "selected_count", "retrieval_method", "strategy", "relation",
    "pending", "call_limit", "round_limit", "timeout_seconds", "batch_size",
    "prompt_tokens", "completion_tokens", "total_tokens", "usage_reported",
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")


def _identifier(value):
    value = str(value) if value is not None else ""
    return value if _IDENTIFIER.fullmatch(value) else "invalid"


def _attributes(values):
    return {key: value if isinstance(value, (bool, int, float)) or value is None else _identifier(value)
            for key, value in values.items() if key in _ATTRIBUTES}


def configure_trace_logging():
    """API 入口调用一次；JSON 独占一行，交给容器日志收集。"""
    if not any(getattr(handler, "classagent_trace", False) for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.classagent_trace = True
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


@dataclass
class Trace:
    request_id: str
    conversation_id: str
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    attributes: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    dropped_events: int = 0
    tools: set = field(default_factory=set)
    counters: dict = field(default_factory=lambda: {
        "model_calls": 0, "model_errors": 0, "tool_calls": 0, "tool_errors": 0,
        "repair_count": 0, "fallback_count": 0, "db_queries": 0, "db_errors": 0,
        "db_duration_ms": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "usage_reported_calls": 0, "usage_missing_calls": 0,
        "prompt_tokens_reported_calls": 0, "completion_tokens_reported_calls": 0,
        "total_tokens_reported_calls": 0,
    })


@dataclass
class Span:
    name: str
    kind: str = "stage"
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])
    attributes: dict = field(default_factory=dict)
    db_queries: int = 0
    db_errors: int = 0
    db_duration_ms: float = 0.0

    def set(self, **attributes):
        self.attributes.update(_attributes(attributes))


def current_trace():
    return _trace.get()


def annotate(**attributes):
    stack = _spans.get()
    if stack:
        stack[-1].set(**attributes)


def bind_request(**attributes):
    state = _trace.get()
    if state is not None:
        state.attributes.update(_attributes(attributes))


def _emit(event, **fields):
    state = _trace.get()
    if state is None:
        return
    try:
        record = {
            "schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event, "trace_id": state.trace_id, "request_id": state.request_id,
            "conversation_id": state.conversation_id, **state.attributes, **fields,
        }
        if event == "span.finished" and record.get("kind") == "tool" and record.get("tool"):
            state.tools.add(record["tool"])
        if event != "span.started":
            if event == "request.finished" or len(state.events) < MAX_TRACE_EVENTS:
                state.events.append(record)
            else:
                state.dropped_events += 1
        LOGGER.info(json.dumps(record, ensure_ascii=False, allow_nan=False))
    except Exception:
        # 观测设施故障不得改变业务结果、重试次数或事务行为。
        pass


def configure_trace_sink(sink):
    """仅由启动入口注入；存储使用独立事务，不依赖业务 Session。"""
    global _sink
    _sink = sink


def _persist(state, *, finished=False):
    if _sink is None:
        return
    token = _trace.set(None)
    spans_token = _spans.set(())
    try:
        _sink(state, finished=finished)
    except Exception:
        # 不输出连接字符串、异常文本等敏感信息。
        try:
            logging.getLogger("classagent.monitoring").warning("trace_persistence_failed")
        except Exception:
            pass
    finally:
        _spans.reset(spans_token)
        _trace.reset(token)


def trace_event(event, **attributes):
    stack = _spans.get()
    state = _trace.get()
    if state is not None:
        if event.endswith(".repair"):
            state.counters["repair_count"] += 1
        elif event.endswith(".fallback"):
            state.counters["fallback_count"] += 1
    _emit(event, span_id=stack[-1].span_id if stack else None, **_attributes(attributes))


@contextmanager
def span(name, *, kind="stage", **attributes):
    item = Span(name=name, kind=kind, attributes=_attributes(attributes))
    state = _trace.get()
    if state is None:
        yield item
        return
    parents = _spans.get()
    token = _spans.set(parents + (item,))
    prefix = {"name": name, "kind": kind, "span_id": item.span_id,
              "parent_span_id": parents[-1].span_id if parents else None}
    if kind in {"model", "tool"}:
        state.counters[kind + "_calls"] += 1
    started = perf_counter()
    _emit("span.started", **prefix, **item.attributes)
    status = "ok"
    try:
        yield item
        if item.attributes.get("error_code"):
            status = "error"
    except BaseException as exc:
        status = "error"
        item.set(error_type=type(exc).__name__)
        if exc.__cause__ is not None:
            item.set(cause_type=type(exc.__cause__).__name__)
        code = getattr(exc, "status_code", None)
        if isinstance(code, int):
            item.set(http_status=code)
        raise
    finally:
        if kind in {"model", "tool"} and status == "error":
            state.counters[kind + "_errors"] += 1
        if kind == "model" and not item.attributes.get("usage_reported"):
            state.counters["usage_missing_calls"] += 1
        _emit("span.finished", **prefix, status=status,
              duration_ms=round((perf_counter() - started) * 1000, 3),
              db_queries=item.db_queries, db_errors=item.db_errors,
              db_duration_ms=round(item.db_duration_ms, 3), **item.attributes)
        _spans.reset(token)


def traced(name, *, kind="stage"):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with span(name, kind=kind):
                result = function(*args, **kwargs)
                if isinstance(result, dict) and isinstance(result.get("outcome"), str):
                    annotate(outcome=result["outcome"])
                return result
        return wrapped
    return decorate


@contextmanager
def request_trace(request_id, conversation_id):
    """同一业务请求重试仍使用相同 request_id，每次尝试有独立 trace_id。"""
    state = Trace(_identifier(request_id), _identifier(conversation_id))
    trace_token = _trace.set(state)
    span_token = _spans.set(())
    started = perf_counter()
    status = "ok"
    _emit("request.started")
    _persist(state)
    try:
        with span("request"):
            yield state
    except BaseException as exc:
        status = "error"
        bind_request(error_type=type(exc).__name__)
        code = getattr(exc, "status_code", None)
        bind_request(outcome="rejected" if isinstance(code, int) and 400 <= code < 500 else "failed")
        if isinstance(code, int):
            bind_request(http_status=code)
        raise
    finally:
        metrics = dict(state.counters)
        metrics["db_duration_ms"] = round(metrics["db_duration_ms"], 3)
        if status == "ok" and state.attributes.get("outcome") == "cancelled":
            status = "cancelled"
        _emit("request.finished", status=status,
              duration_ms=round((perf_counter() - started) * 1000, 3), **metrics)
        _persist(state, finished=True)
        _spans.reset(span_token)
        _trace.reset(trace_token)


def record_usage(usage):
    """只采用供应商返回的非负整数；缺报不估算为真实用量。"""
    if not isinstance(usage, dict):
        return
    stack = _spans.get()
    state = _trace.get()
    if state is None or not stack or stack[-1].kind != "model":
        return
    values = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
              if type(usage.get(key)) is int and usage[key] >= 0}
    if not values or stack[-1].attributes.get("usage_reported"):
        return
    stack[-1].set(usage_reported=True, **values)
    state.counters["usage_reported_calls"] += 1
    for key, value in values.items():
        state.counters[key] += value
        state.counters[key + "_reported_calls"] += 1


def install_sql_metrics():
    """每条 SQL 只累计一次；各 span 的数据库耗时包含子 span，不可相加。"""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    for name, callback in (("before_cursor_execute", _sql_start),
                           ("after_cursor_execute", _sql_end), ("handle_error", _sql_error)):
        if not event.contains(Engine, name, callback):
            event.listen(Engine, name, callback)


def _sql_start(conn, cursor, statement, parameters, context, executemany):
    if _trace.get() is not None:
        context._classagent_timing = (_trace.get(), _spans.get(), perf_counter())


def _finish_sql(context, failed=False):
    measurement = getattr(context, "_classagent_timing", None)
    if measurement is None:
        return
    context._classagent_timing = None
    state, parents, started = measurement
    duration = (perf_counter() - started) * 1000
    state.counters["db_queries"] += 1
    state.counters["db_errors"] += int(failed)
    state.counters["db_duration_ms"] += duration
    for item in parents:
        item.db_queries += 1
        item.db_errors += int(failed)
        item.db_duration_ms += duration


def _sql_end(conn, cursor, statement, parameters, context, executemany):
    _finish_sql(context)


def _sql_error(exception_context):
    _finish_sql(exception_context.execution_context, failed=True)

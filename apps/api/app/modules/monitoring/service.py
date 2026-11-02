from datetime import datetime, timedelta, timezone
from math import ceil

from fastapi import HTTPException
from sqlalchemy import case, func, select

from ...shared.models import User
from .models import AgentTrace


def current_user(db, username):
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(401, "登录已过期，请重新登录")
    return user


def require_admin(db, username):
    user = current_user(db, username)
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可查看运行监控")
    return user


def trace_status(now):
    # 没有结束记录不代表业务失败；超 30 分钟仅标记待排查。
    return case((
        (AgentTrace.status == "running") & (AgentTrace.started_at < now - timedelta(minutes=30)),
        "incomplete"), else_=AgentTrace.status)


def filters(*, since, until, status, request_id, tool, now):
    if since.tzinfo is None or until.tzinfo is None:
        raise HTTPException(422, "时间参数必须携带时区")
    if since >= until or until - since > timedelta(days=31):
        raise HTTPException(422, "时间范围需大于零且不超过 31 天")
    conditions = [AgentTrace.started_at >= since, AgentTrace.started_at < until]
    if status:
        conditions.append(trace_status(now) == status)
    if request_id:
        conditions.append(AgentTrace.request_id == request_id)
    if tool:
        # 工具名来自 allowlist，不对 JSON 文本进行模糊搜索。
        from .tool_index import TraceTool
        conditions.append(AgentTrace.trace_id.in_(select(TraceTool.trace_id).where(TraceTool.tool == tool)))
    return conditions


def iso(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


def serialize(row, *, now=None, detail=False):
    now = now or datetime.now(timezone.utc)
    started = row.started_at.replace(tzinfo=row.started_at.tzinfo or timezone.utc)
    status = "incomplete" if row.status == "running" and started < now - timedelta(minutes=30) else row.status
    result = {
        "trace_id": row.trace_id, "request_id": row.request_id,
        "conversation_id": row.conversation_id, "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at), "status": status, "outcome": row.outcome,
        "duration_ms": row.duration_ms, "metrics": row.metrics,
        "dropped_events": row.dropped_events,
    }
    if detail:
        result.update(attributes=row.attributes, events=row.events)
    return result


def overview(db, conditions, now):
    finished = AgentTrace.finished_at.is_not(None)
    summary = db.execute(select(
        func.count().label("total"),
        func.sum(case((finished, 1), else_=0)).label("finished"),
        *[func.sum(case((trace_status(now) == code, 1), else_=0)).label(code)
          for code in ("ok", "error", "cancelled", "running", "incomplete")],
    ).where(*conditions)).mappings().one()
    values = {key: int(value or 0) for key, value in summary.items()}
    metrics_keys = ("model_calls", "model_errors", "tool_calls", "tool_errors", "repair_count",
                    "fallback_count", "db_queries", "db_errors", "prompt_tokens", "completion_tokens",
                    "total_tokens", "usage_reported_calls", "usage_missing_calls",
                    "prompt_tokens_reported_calls", "completion_tokens_reported_calls", "total_tokens_reported_calls")
    metrics = db.execute(select(*[
        func.coalesce(func.sum(AgentTrace.metrics[key].as_integer()), 0).label(key)
        for key in metrics_keys
    ]).where(*conditions, finished)).mappings().one()
    durations = select(AgentTrace.duration_ms).where(*conditions, finished, AgentTrace.duration_ms.is_not(None))
    duration_count = db.scalar(select(func.count()).select_from(durations.subquery()))
    def percentile(p):
        if not duration_count:
            return None
        return db.scalar(durations.order_by(AgentTrace.duration_ms).offset(ceil(duration_count * p) - 1).limit(1))
    outcomes = db.execute(select(AgentTrace.outcome, func.count()).where(*conditions, finished)
                          .group_by(AgentTrace.outcome)).all()
    return {**values, "metrics": dict(metrics), "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "outcomes": {key or "unspecified": count for key, count in outcomes},
            "normal_return_rate": values["ok"] / values["finished"] if values["finished"] else None}

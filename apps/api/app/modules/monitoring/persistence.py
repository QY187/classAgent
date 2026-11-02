"""独立连接池、短事务、失败放行；不计入业务 SQL 指标。"""
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ...core.config import get_settings
from ...core.telemetry import configure_trace_sink
from .models import AgentTrace
from .tool_index import TraceTool


def trace_writer(session_factory):
    def persist(state, *, finished=False):
        start = state.events[0]
        end = state.events[-1] if finished else None
        with session_factory() as db:
            row = db.get(AgentTrace, state.trace_id)
            if row is None:
                row = AgentTrace(
                    trace_id=state.trace_id, request_id=state.request_id,
                    conversation_id=state.conversation_id,
                    started_at=datetime.fromisoformat(start["timestamp"]), status="running",
                )
                db.add(row)
            if finished:
                row.finished_at = datetime.fromisoformat(end["timestamp"])
                row.status = end["status"]
                row.duration_ms = end["duration_ms"]
                row.user_id = state.attributes.get("user_id")
                row.outcome = state.attributes.get("outcome")
                row.metrics = dict(state.counters)
                row.attributes = dict(state.attributes)
                row.events = list(state.events)
                row.dropped_events = state.dropped_events
                for tool in sorted(state.tools):
                    db.merge(TraceTool(trace_id=state.trace_id, tool=tool))
            db.commit()
    return persist


def start_persistence():
    # 复用数据库但隔离业务连接池，限制观测故障对聊天耗时的影响。
    url = get_settings().database_url
    options = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        options.update(pool_size=2, max_overflow=0, pool_timeout=0.2,
                       connect_args={"connect_timeout": 2,
                                     "options": "-c statement_timeout=2000 -c lock_timeout=500"})
    engine = create_engine(url, **options)
    configure_trace_sink(trace_writer(sessionmaker(bind=engine, expire_on_commit=False)))
    return engine

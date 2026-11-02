from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from ...core.db import get_db
from ...core.deps import get_current_user
from . import service
from .models import AgentTrace
from .tool_index import TraceTool

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def admin(username=Depends(get_current_user), db: Session = Depends(get_db)):
    return service.require_admin(db, username)


def trace_filters(
    since: datetime | None = None, until: datetime | None = None,
    status: Literal["ok", "error", "cancelled", "running", "incomplete"] | None = None,
    request_id: str | None = Query(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$"),
    tool: str | None = Query(None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$"),
):
    now = datetime.now(timezone.utc)
    until = until or now
    return service.filters(since=since or until - timedelta(days=1), until=until, status=status,
                           request_id=request_id, tool=tool, now=now), now


@router.get("/overview", dependencies=[Depends(admin)])
def overview(db: Session = Depends(get_db), query=Depends(trace_filters)):
    conditions, now = query
    return service.overview(db, conditions, now)


@router.get("/tools", dependencies=[Depends(admin)])
def tools(db: Session = Depends(get_db), query=Depends(trace_filters)):
    conditions, _ = query
    return list(db.scalars(select(TraceTool.tool).where(TraceTool.trace_id.in_(
        select(AgentTrace.trace_id).where(*conditions))).distinct().order_by(TraceTool.tool)))


@router.get("/traces", dependencies=[Depends(admin)])
def traces(db: Session = Depends(get_db), query=Depends(trace_filters),
           page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100)):
    conditions, now = query
    total = db.scalar(select(func.count()).select_from(AgentTrace).where(*conditions))
    rows = db.scalars(select(AgentTrace).where(*conditions)
                      .order_by(AgentTrace.started_at.desc(), AgentTrace.trace_id.desc())
                      .offset((page - 1) * page_size).limit(page_size)
                      .options(defer(AgentTrace.events), defer(AgentTrace.attributes)))
    return {"total": total, "page": page, "page_size": page_size,
            "items": [service.serialize(row, now=now) for row in rows]}


@router.get("/traces/{trace_id}", dependencies=[Depends(admin)])
def trace_detail(trace_id: str, db: Session = Depends(get_db)):
    row = db.get(AgentTrace, trace_id)
    if row is None:
        raise HTTPException(404, "追踪记录不存在")
    return service.serialize(row, detail=True)


@router.get("/requests/{request_id}")
def own_request(request_id: str, conversation_id: str | None = Query(None, max_length=128),
                username=Depends(get_current_user), db: Session = Depends(get_db)):
    user = service.current_user(db, username)
    # 即使是管理员，从聊天入口也仅返回自己的记录。
    conditions = [AgentTrace.request_id == request_id, AgentTrace.user_id == user.id]
    if conversation_id:
        conditions.append(AgentTrace.conversation_id == conversation_id)
    rows = list(db.scalars(select(AgentTrace).where(*conditions)
                           .order_by(AgentTrace.started_at.desc(), AgentTrace.trace_id.desc()).limit(20)))
    if not rows:
        raise HTTPException(404, "暂无可查看的追踪记录")
    return {"items": [service.serialize(row, detail=True) for row in rows]}

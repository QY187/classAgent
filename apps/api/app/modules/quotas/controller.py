from datetime import date, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ...core.db import get_db
from ...core.deps import get_current_user
from ...shared.models import User, now_utc
from ..monitoring.service import current_user
from . import service
from .models import TokenUsageEntry

router = APIRouter(prefix="/quotas", tags=["token-quotas"])


class LimitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    daily_limit: int | None = Field(ge=0, le=1000000000)


class UsageResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actual_tokens: int = Field(ge=0, le=1000000000)


def admin(username=Depends(get_current_user), db: Session = Depends(get_db)):
    user = current_user(db, username)
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可管理 Token 额度")
    return user


def entry_data(row):
    return {"id": row.id, "day": row.day.isoformat(), "model": row.model, "purpose": row.purpose,
            "status": row.status, "reserved_tokens": row.reserved_tokens, "actual_tokens": row.actual_tokens,
            "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
            "created_at": row.created_at, "finished_at": row.finished_at, "resolved_by": row.resolved_by}


@router.get("/me")
def mine(username=Depends(get_current_user), db: Session = Depends(get_db)):
    return service.snapshot(db, current_user(db, username).id)


@router.get("/me/entries")
def my_entries(day: date | None = None, page: int = Query(1, ge=1, le=10000),
               username=Depends(get_current_user), db: Session = Depends(get_db)):
    return entries(db, current_user(db, username).id, day, page)


def entries(db, user_id, day, page):
    conditions = [TokenUsageEntry.user_id == user_id, TokenUsageEntry.day == (day or service.today())]
    count = db.scalar(select(func.count()).select_from(TokenUsageEntry).where(*conditions))
    rows = db.scalars(select(TokenUsageEntry).where(*conditions).order_by(TokenUsageEntry.created_at.desc(), TokenUsageEntry.id.desc())
                      .offset((page - 1) * 20).limit(20))
    return {"items": [entry_data(row) for row in rows], "total": count, "page": page, "page_size": 20}


@router.get("/admin/users", dependencies=[Depends(admin)])
def users(query: str = Query("", max_length=100), page: int = Query(1, ge=1, le=10000), db: Session = Depends(get_db)):
    conditions = [User.username.contains(query, autoescape=True)] if query else []
    count = db.scalar(select(func.count()).select_from(User).where(*conditions))
    rows = db.scalars(select(User).where(*conditions).order_by(User.created_at, User.id).offset((page - 1) * 20).limit(20))
    return {"items": [{"username": row.username, **service.snapshot(db, row.id)} for row in rows],
            "page": page, "page_size": 20, "total": count}


@router.put("/admin/users/{user_id}")
def update_limit(user_id: str, payload: LimitUpdate, actor=Depends(admin), db: Session = Depends(get_db)):
    return service.change_limit(db, user_id, payload.daily_limit, actor.id)


@router.get("/admin/users/{user_id}/entries", dependencies=[Depends(admin)])
def user_entries(user_id: str, day: date | None = None, page: int = Query(1, ge=1, le=10000), db: Session = Depends(get_db)):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")
    return entries(db, user_id, day, page)


@router.put("/admin/entries/{entry_id}/resolve")
def resolve_entry(entry_id: str, payload: UsageResolution, actor=Depends(admin), db: Session = Depends(get_db)):
    row = db.get(TokenUsageEntry, entry_id)
    if row is None:
        raise HTTPException(404, "用量记录不存在")
    created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    if row.status != "uncertain" and not (row.status == "reserved" and now_utc() - created >= timedelta(minutes=15)):
        raise HTTPException(409, "仅可核对待确认或超过 15 分钟仍未结束的预留记录")
    user_id = row.user_id
    db.rollback()
    sessions = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    if not service.settle(sessions, entry_id, payload.actual_tokens, actor_id=actor.id):
        raise HTTPException(409, "此用量记录已经完成结算")
    return service.snapshot(db, user_id)

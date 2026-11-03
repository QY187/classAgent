"""原子预留及幂等结算；跨日结算仍归入调用发起日，不通过定时清零。"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ...core.config import get_settings
from ...core.chat_failures import ChatRequestFailure
from ...shared.models import User, new_id, now_utc
from .models import DailyTokenUsage, TokenQuotaChange, TokenUsageEntry, UserTokenQuota

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def today(now=None):
    return (now or now_utc()).astimezone(SHANGHAI).date()


def _insert_once(db, model, values, keys):
    statement = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(statement(model).values(**values).on_conflict_do_nothing(index_elements=keys))


def _policy(db, user_id):
    _insert_once(db, UserTokenQuota, {"user_id": user_id, "daily_limit": None, "updated_at": now_utc()}, ["user_id"])
    return db.scalar(select(UserTokenQuota).where(UserTokenQuota.user_id == user_id).with_for_update())


def effective_limit(policy):
    return policy.daily_limit if policy and policy.daily_limit is not None else get_settings().daily_token_limit


def reserve(sessions, user_id, amount, *, model, purpose, now=None):
    if amount <= 0:
        raise ValueError("额度预留必须为正数")
    day = today(now)
    with sessions() as db, db.begin():
        if db.get(User, user_id) is None:
            raise ChatRequestFailure("quota_identity_required")
        limit = effective_limit(_policy(db, user_id))
        _insert_once(db, DailyTokenUsage, {"user_id": user_id, "day": day, "used_tokens": 0, "reserved_tokens": 0}, ["user_id", "day"])
        # 条件 UPDATE 在多进程/并发下仍只让可用额度足够的预留成功。
        result = db.execute(update(DailyTokenUsage).where(DailyTokenUsage.user_id == user_id,
            DailyTokenUsage.day == day, DailyTokenUsage.used_tokens + DailyTokenUsage.reserved_tokens + amount <= limit
        ).values(reserved_tokens=DailyTokenUsage.reserved_tokens + amount))
        if result.rowcount != 1:
            raise ChatRequestFailure("quota_exhausted")
        entry_id = new_id()
        db.add(TokenUsageEntry(id=entry_id, user_id=user_id, day=day, model=model[:100], purpose=purpose[:40],
                               reserved_tokens=amount, status="reserved", created_at=now or now_utc()))
    return entry_id


def settle(sessions, entry_id, actual, *, input_tokens=None, output_tokens=None, actor_id=None):
    if type(actual) is not int or actual < 0:
        raise ValueError("实际用量必须为非负整数")
    with sessions() as db, db.begin():
        row = db.get(TokenUsageEntry, entry_id)
        if row is None:
            raise HTTPException(404, "用量记录不存在")
        status = "settled" if actual else "released"
        changed = db.execute(update(TokenUsageEntry).where(TokenUsageEntry.id == entry_id,
            TokenUsageEntry.status.in_(["reserved", "uncertain"])).values(status=status,
            actual_tokens=actual, input_tokens=input_tokens, output_tokens=output_tokens,
            finished_at=now_utc(), resolved_by=actor_id))
        if changed.rowcount != 1:
            return False
        db.execute(update(DailyTokenUsage).where(DailyTokenUsage.user_id == row.user_id,
            DailyTokenUsage.day == row.day).values(used_tokens=DailyTokenUsage.used_tokens + actual,
                                                 reserved_tokens=DailyTokenUsage.reserved_tokens - row.reserved_tokens))
    return True


def uncertain(sessions, entry_id):
    with sessions() as db, db.begin():
        db.execute(update(TokenUsageEntry).where(TokenUsageEntry.id == entry_id,
            TokenUsageEntry.status == "reserved").values(status="uncertain"))


def snapshot(db, user_id, *, now=None):
    day = today(now)
    policy = db.get(UserTokenQuota, user_id)
    usage = db.get(DailyTokenUsage, (user_id, day))
    limit = effective_limit(policy)
    used, reserved = (usage.used_tokens, usage.reserved_tokens) if usage else (0, 0)
    next_reset = datetime.combine(day + timedelta(days=1), datetime.min.time(), SHANGHAI)
    return {"user_id": user_id, "day": day.isoformat(), "timezone": "Asia/Shanghai", "resets_at": next_reset.isoformat(),
            "enabled": get_settings().token_quota_enabled, "daily_limit": limit,
            "custom_daily_limit": policy.daily_limit if policy else None, "default_daily_limit": get_settings().daily_token_limit,
            "used_tokens": used, "reserved_tokens": reserved, "remaining_tokens": max(0, limit - used - reserved),
            "scope": "llm", "scope_label": "大模型输入与输出 Token（含内部调用及后台纪要）"}


def change_limit(db, user_id, daily_limit, actor_id):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")
    policy = _policy(db, user_id)
    db.add(TokenQuotaChange(user_id=user_id, actor_id=actor_id, previous_limit=policy.daily_limit, daily_limit=daily_limit))
    policy.daily_limit, policy.updated_by, policy.updated_at = daily_limit, actor_id, now_utc()
    db.commit()
    return snapshot(db, user_id)

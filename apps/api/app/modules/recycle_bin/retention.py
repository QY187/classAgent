"""回收站保留期限：从各对象自己的删除时间起算 30 天。"""
from datetime import datetime, timedelta, timezone

RETENTION_DAYS = 30


def expires_at(deleted_at: datetime) -> datetime:
    # SQLite 测试及旧时间值可能没有时区；数据库删除时间统一按 UTC 写入。
    return deleted_at.replace(tzinfo=timezone.utc) + timedelta(days=RETENTION_DAYS) if deleted_at.tzinfo is None else deleted_at + timedelta(days=RETENTION_DAYS)


def is_expired(deleted_at: datetime, now: datetime) -> bool:
    return expires_at(deleted_at) <= now

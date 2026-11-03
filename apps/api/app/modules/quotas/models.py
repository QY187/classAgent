from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base
from ...shared.models import new_id, now_utc


class UserTokenQuota(Base):
    __tablename__ = "user_token_quotas"
    __table_args__ = (CheckConstraint("daily_limit IS NULL OR daily_limit >= 0"),)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    daily_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class DailyTokenUsage(Base):
    __tablename__ = "daily_token_usage"
    __table_args__ = (CheckConstraint("used_tokens >= 0 AND reserved_tokens >= 0"),)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    used_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, default=0)


class TokenUsageEntry(Base):
    __tablename__ = "token_usage_entries"
    __table_args__ = (Index("ix_token_usage_owner_day", "user_id", "day", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    model: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    reserved_tokens: Mapped[int] = mapped_column(BigInteger)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class TokenQuotaChange(Base):
    __tablename__ = "token_quota_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    previous_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    daily_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

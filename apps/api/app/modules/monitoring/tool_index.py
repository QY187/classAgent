from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.db import Base


class TraceTool(Base):
    """按执行工具筛选的轻量索引，避免扫描全部阶段 JSON。"""
    __tablename__ = "agent_trace_tools"
    trace_id: Mapped[str] = mapped_column(ForeignKey("agent_traces.trace_id", ondelete="CASCADE"), primary_key=True)
    tool: Mapped[str] = mapped_column(String(128), primary_key=True, index=True)

import logging
import json
from ...core.config import get_settings
from ...core.telemetry import traced, annotate
from sqlalchemy import select
from ...shared.models import ChatConversation
from ..memory.context import build_context, completed_pairs, MemoryContext, safe_text, cost, references_cost
from ..memory.recall import recall

logger=logging.getLogger(__name__)


@traced("memory.context")
def recent_context(db, conversation_id, before_position, question="", *, budget=None):
    budget=budget or get_settings().memory_context_budget
    try:
        with db.begin_nested():
            context=build_context(db,conversation_id,before_position,budget=budget)
            def remaining():
                return max(0,budget-sum(cost(m["content"]) for m in context)
                    -references_cost(context.references))
            if question:
                conversation=db.scalar(select(ChatConversation).where(ChatConversation.id==conversation_id))
                if conversation:
                    context.references.extend(recall(db,conversation,question,before_position,budget=min(1600,remaining())))
            annotate(result_count=len(context.references),strategy="budgeted_memory")
            return context
    except Exception:
        # 保存点回滚仅记忆读取；当前待回答消息和业务事务仍在。
        annotate(reason="memory_unavailable",strategy="recent_only")
        logger.warning("Memory context unavailable; using recent turns")
        rows=[]
        for pair in reversed(completed_pairs(db,conversation_id,before_position)):
            messages=[{"role":r.role,"content":safe_text(r.content)} for r in pair]
            used=sum(cost(m["content"]) for m in messages)
            if used>budget:break
            rows[0:0]=messages;budget-=used
        return MemoryContext(rows)

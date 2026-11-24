"""模型调用前的压力检测与同步滚动压缩；后台摘要只作为预热。"""
from time import monotonic
from dataclasses import replace
from sqlalchemy import select
from ...core.config import get_settings
from ...core.chat_failures import ChatRequestFailure
from ...core.telemetry import traced,annotate
from ...shared.models import ChatConversation,ConversationMemorySummary
from ..chat.generation import GenerationStopped
from .context import completed_pairs,summary_references,references_cost,cost,safe_text
from .settings import effective_settings
from .summaries import update_summary


def pressure(db,conversation_id,before_position):
    summary=db.get(ConversationMemorySummary,conversation_id)
    refs=summary_references(db,conversation_id,before_position,24000)
    through=summary.through_position if summary and refs and summary.through_position<before_position else -1
    pairs=completed_pairs(db,conversation_id,before_position,after_position=through,limit=None)
    return pairs,sum(cost(safe_text(row.content)) for pair in pairs for row in pair)+references_cost(refs)


@traced("memory.compaction")
def ensure_compacted(db,conversation_id,before_position,budget,*,on_check=None,on_step=None):
    conversation=db.scalar(select(ChatConversation).where(ChatConversation.id==conversation_id))
    if not conversation or not effective_settings(db,conversation.user_id,conversation_id)["history_enabled"]:
        return
    pairs,used=pressure(db,conversation_id,before_position)
    if not get_settings().memory_summary_enabled:
        if used>budget:raise ChatRequestFailure("context_compaction_failed")
        return
    threshold=int(budget*0.8)
    if used<=threshold:return
    step={"id":"memory-compaction","tool":"compact_context"}
    if on_step:on_step(step|{"status":"running"})
    started=monotonic()
    try:
        for attempt in range(3):
            if on_check:on_check()
            pairs,used=pressure(db,conversation_id,before_position)
            if used<=threshold:break
            keep=min(2,len(pairs))
            # 最新轮次特别长时也可压缩，不能因固定保留数而直接丢弃它。
            while keep and sum(cost(safe_text(r.content)) for pair in pairs[-keep:] for r in pair)>budget//2:
                keep-=1
            if keep==len(pairs) and keep:keep-=1
            remaining=45-(monotonic()-started)
            if remaining<=1:raise RuntimeError("Compaction deadline")
            update_summary(db,conversation_id,before_position=before_position,force=True,keep_pairs=keep,
                target_budget=max(200,budget//3),timeout=min(20,remaining),on_check=on_check)
            db.expire_all()
        if on_check:on_check()
        _,used=pressure(db,conversation_id,before_position)
        # 压缩后允许阈值与硬预算间的余量；绝不静默丢掉未压缩的旧前缀继续回答。
        if used>budget:raise RuntimeError("Compaction incomplete")
        if on_step:on_step(step|{"status":"completed"})
        annotate(strategy="synchronous_checkpoint",result_count=len(pairs))
    except GenerationStopped:
        raise
    except Exception as exc:
        if on_step:on_step(step|{"status":"failed","error_code":"context_compaction_failed"})
        if isinstance(exc,ChatRequestFailure):
            if exc.failure.code.startswith("quota_"):
                raise
            raise ChatRequestFailure(replace(exc.failure,reason="整理较早对话时，"+exc.failure.reason+" 本轮暂停，原聊天记录仍保留。")) from exc
        raise ChatRequestFailure("context_compaction_failed") from exc

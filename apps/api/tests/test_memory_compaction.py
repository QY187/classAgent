import json
from unittest.mock import patch
import pytest
from app.core.chat_failures import ChatRequestFailure
from app.shared.models import ChatMessage,ConversationMemorySummary
from app.modules.memory.context import build_context,cost,references_cost
from app.modules.memory.compaction import ensure_compacted,pressure
from app.modules.memory import summaries
from test_memory_context import db,pair


def answer_from_sources(messages,*args,**kwargs):
    sources=json.loads(messages[-1]["content"])
    # 测试替身仅保存明确约束，其他普通内容不进入摘要。
    chosen=next(s for s in sources if "明确约定" in s["text"])
    return {"content":json.dumps([{"source_id":chosen["source_id"],"text":chosen["text"][:80]}])}


def populate(db,start=0,end=16):
    for n in range(start,end):pair(db,n,("明确约定：使用Python解释树遍历。" if n==0 else f"第{n}个问题：讨论树遍历。")+"补充说明"*12,"这是对二叉树前中后序遍历的解释。"*12)


def test_pressure_compacts_and_keeps_uncovered_tail(db,monkeypatch):
    populate(db)
    original=db.query(ChatMessage).count()
    events=[]
    monkeypatch.setattr(summaries,"complete",answer_from_sources)
    ensure_compacted(db,"c",32,6000,on_step=events.append)
    checkpoint=db.get(ConversationMemorySummary,"c")
    assert checkpoint and checkpoint.through_position<31
    context=build_context(db,"c",32,budget=6000)
    assert "Python" in str(context.references)
    assert context[-1]["content"].startswith("这是对二叉树")
    assert len(context)<32
    assert sum(cost(m["content"]) for m in context)+references_cost(context.references)<=6000
    assert db.query(ChatMessage).count()==original
    assert [e["status"] for e in events]==["running","completed"]
    # 检查点前缀不重复注入近期消息。
    assert not any(m["content"].startswith("明确约定") for m in context)
    with patch.object(summaries,"complete") as call:
        ensure_compacted(db,"c",32,6000)
        call.assert_not_called()


def test_compaction_failure_stops_before_agent_and_preserves_records(db,monkeypatch):
    populate(db)
    monkeypatch.setattr(summaries,"complete",lambda *a,**k: (_ for _ in ()).throw(RuntimeError("unavailable")))
    with pytest.raises(ChatRequestFailure) as error:ensure_compacted(db,"c",32,6000)
    assert error.value.failure.code=="context_compaction_failed"
    assert db.query(ChatMessage).count()==32
    assert db.get(ConversationMemorySummary,"c").through_position==-1
    from app.modules.chat.sending import send_message
    with patch("app.modules.memory.compaction.ensure_compacted",side_effect=ChatRequestFailure("context_compaction_failed")),patch("app.modules.chat.sending.resolve_turn_intent") as planning,patch("app.modules.chat.sending.run_agent") as agent:
        with pytest.raises(ChatRequestFailure):send_message(db,"c","u","继续前面的约定","request-after-pressure")
        planning.assert_not_called();agent.assert_not_called()


def test_rolling_checkpoint_retains_old_constraints(db,monkeypatch):
    populate(db)
    monkeypatch.setattr(summaries,"complete",answer_from_sources)
    ensure_compacted(db,"c",32,6000)
    version=db.get(ConversationMemorySummary,"c").version
    populate(db,16,30)
    ensure_compacted(db,"c",60,6000)
    assert db.get(ConversationMemorySummary,"c").version>version
    assert "Python" in str(build_context(db,"c",60).references)


def test_empty_summary_cannot_claim_coverage(db,monkeypatch):
    populate(db)
    monkeypatch.setattr(summaries,"complete",lambda *a,**k:{"content":"[]"})
    with pytest.raises(ChatRequestFailure):ensure_compacted(db,"c",32,6000)
    assert db.get(ConversationMemorySummary,"c").through_position==-1


def test_sending_publishes_compaction_before_agent(db,monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(),"memory_context_budget",6000)
    from app.modules.chat.sending import send_message
    from app.modules.chat.intent_schema import TurnDecision
    populate(db)
    monkeypatch.setattr(summaries,"complete",answer_from_sources)
    events=[]
    def answer(*args,**kwargs):
        assert db.get(ConversationMemorySummary,"c").through_position>=0
        assert events and events[-1]["steps"][0]["status"]=="completed"
        assert "Python" in str(kwargs["history"].references)
        return {"answer":"继续按约定讲解。","citations":[],"outcome":"answered"}
    with patch("app.modules.chat.sending.resolve_turn_intent",return_value=TurnDecision.model_validate({"relation":"new","intent":{}})),patch("app.modules.chat.sending.run_agent",side_effect=answer):
        result=send_message(db,"c","u","继续最早的约定","compacted-request",on_step=events.append)
    assert result["messages"][-1]["content"]=="继续按约定讲解。"
    assert any(step["label"]=="压缩较早对话，保留近期上下文" for event in events for step in event["steps"])


def test_old_history_over_200_messages_advances_without_silent_gap(db,monkeypatch):
    populate(db,0,110)
    monkeypatch.setattr(summaries,"complete",answer_from_sources)
    with pytest.raises(ChatRequestFailure):ensure_compacted(db,"c",220,6000)
    checkpoint=db.get(ConversationMemorySummary,"c")
    assert checkpoint.through_position>0
    assert "Python" in checkpoint.summary_json
    # 单次有时间/批次数上限，重试从已提交检查点继续，不能跳过早期前缀。
    ensure_compacted(db,"c",220,6000)
    assert "Python" in str(build_context(db,"c",220).references)
    assert pressure(db,"c",220)[1]<=6000


def test_cancel_during_compaction_does_not_save_result(db,monkeypatch):
    from app.modules.chat.generation import GenerationStopped
    populate(db)
    monkeypatch.setattr(summaries,"complete",answer_from_sources)
    calls=[]
    def check():
        calls.append(1)
        if len(calls)>=3:raise GenerationStopped()
    with pytest.raises(GenerationStopped):ensure_compacted(db,"c",32,6000,on_check=check)
    assert db.get(ConversationMemorySummary,"c").through_position==-1

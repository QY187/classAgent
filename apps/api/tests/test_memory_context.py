import json
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from app.core.db import Base
from app.shared.models import User, ChatConversation, ChatMessage, ConversationMemorySummary
from app.modules.memory.context import build_context, cost
from app.modules.memory import summaries


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id="u", username="u", password_hash="x")); session.flush()
        session.add(ChatConversation(id="c", user_id="u", title="test")); session.commit()
        yield session


def pair(db, n, question="继续讨论树遍历", answer="这是过去的回答"):
    db.add_all([ChatMessage(id=f"u{n}", conversation_id="c", request_id=f"r{n}", position=n*2,
        role="user", content=question), ChatMessage(id=f"a{n}", conversation_id="c", request_id=f"r{n}",
        position=n*2+1, role="assistant", content=answer)])
    db.commit()


def test_complete_pairs_and_budget(db):
    for n in range(12): pair(db, n)
    context = build_context(db, "c", 24)
    assert len(context) > 8
    assert sum(cost(x["content"]) for x in context) <= 4500
    assert context[-1]["role"] == "assistant"
    db.add(ChatMessage(conversation_id="c", request_id="pending", position=24, role="user", content="未回答", status="failed")); db.commit()
    assert build_context(db, "c", 25) == context


def test_no_partial_pair_or_secret(db):
    pair(db, 0, "密码：sensitive-value", "收到")
    pair(db, 1, "中"*5000, "long")
    assert build_context(db, "c", 4, budget=6000) == []
    assert "sensitive-value" not in str(build_context(db, "c", 2))


def test_summary_requires_live_source_and_exact_quote(db):
    pair(db, 0)
    db.add(ConversationMemorySummary(conversation_id="c", through_position=1,
        summary_json=json.dumps([{"source_id":"u0", "text":"树遍历"}, {"source_id":"a0", "text":"编造内容"}]))); db.commit()
    context = build_context(db, "c", 2)
    assert len(context.references) == 1
    db.delete(db.get(ChatMessage,"u0")); db.commit()
    assert not build_context(db,"c",2).references


def test_summary_incremental_and_ungrounded_rejected(db, monkeypatch):
    for n in range(10): pair(db,n,"树遍历"*80,"回答"*80)
    monkeypatch.setattr(summaries,"get_settings",lambda:SimpleNamespace(memory_summary_enabled=True))
    monkeypatch.setattr(summaries,"complete",lambda *a,**k:{"content":json.dumps([{"source_id":"u0","text":"树遍历"}])})
    assert summaries.update_summary(db,"c")
    summary=db.get(ConversationMemorySummary,"c")
    assert summary.version==1 and summary.through_position==11
    assert not summaries.update_summary(db,"c")
    for n in range(10,16): pair(db,n,"树遍历"*80,"回答"*80)
    monkeypatch.setattr(summaries,"complete",lambda *a,**k:{"content":json.dumps([{"source_id":"u0","text":"没有来源的结论"}])})
    with pytest.raises(ValueError): summaries.update_summary(db,"c")
    assert db.get(ConversationMemorySummary,"c").version==1


def test_summary_compare_and_swap_does_not_overwrite_newer_result(db,monkeypatch):
    from sqlalchemy import update
    for n in range(10): pair(db,n,"树遍历"*80,"回答"*80)
    def concurrent(*args,**kwargs):
        db.execute(update(ConversationMemorySummary).where(ConversationMemorySummary.conversation_id=="c").values(version=9,summary_json="[]"));db.commit()
        return {"content":json.dumps([{"source_id":"u0","text":"树遍历"}])}
    monkeypatch.setattr(summaries,"complete",concurrent)
    assert not summaries.update_summary(db,"c")
    assert db.get(ConversationMemorySummary,"c").version==9


def test_context_failure_preserves_pending_turn(db,monkeypatch):
    from app.modules.chat import context as chat_context
    pair(db,0)
    pending=ChatMessage(conversation_id="c",request_id="pending",position=2,role="user",content="继续",status="pending")
    db.add(pending);db.flush()
    monkeypatch.setattr(chat_context,"build_context",lambda *a,**k: (_ for _ in ()).throw(RuntimeError("memory unavailable")))
    result=chat_context.recent_context(db,"c",2,"继续")
    assert len(result)==2 and not result.references
    db.commit()
    assert db.get(ChatMessage,pending.id).status=="pending"


def test_latest_complete_turn_can_borrow_memory_reservation(db):
    pair(db,0,"解释这部分内容","中"*2100)
    context=build_context(db,"c",2)
    assert len(context)==2 and context[-1]["content"]=="中"*2100
    assert sum(cost(m["content"]) for m in context)<=6000

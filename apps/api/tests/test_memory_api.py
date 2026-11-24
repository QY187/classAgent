import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event,select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core.db import Base,get_db
from app.core.deps import get_current_user
from app.shared.models import User,Course,ChatConversation,ChatMessage,UserMemory,ConversationMemorySummary
from app.modules.memory.controller import router
from app.modules.memory.service import explicit_command,long_term_references
from app.modules.memory.context import build_context
from app.modules.memory.recall import recall


@pytest.fixture
def api():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    @event.listens_for(engine,"connect")
    def fk(conn,_):conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    db=Session(engine)
    db.add_all([User(id="u",username="u",password_hash="x"),User(id="v",username="v",password_hash="x")]);db.flush()
    db.add_all([Course(id="course",owner_id="u",name="树"),Course(id="other",owner_id="v",name="他人")]);db.flush()
    db.add_all([ChatConversation(id="c",user_id="u",title="main"),ChatConversation(id="d",user_id="u",course_id="course",title="course"),ChatConversation(id="v",user_id="v",title="other")]);db.commit()
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_user]=lambda:"u"
    with TestClient(app) as client:yield client,db,app
    db.close()


def test_crud_isolation_and_conflicts(api):
    client,db,app=api
    row=client.post("/memories",json={"content":"先举例再给代码"}).json()
    assert row["version"]==1
    assert client.patch("/memories/"+row["id"],json={"content":"先讲概念","version":1}).status_code==200
    assert client.patch("/memories/"+row["id"],json={"content":"旧页面覆盖","version":1}).status_code==409
    app.dependency_overrides[get_current_user]=lambda:"v"
    assert client.get("/memories").json()==[]
    assert client.delete("/memories/"+row["id"]).status_code==404
    app.dependency_overrides[get_current_user]=lambda:"u"
    assert client.post("/memories",json={"content":"喜欢中文","course_id":"other"}).status_code==404
    assert client.post("/memories",json={"content":"密码：not-real"}).status_code==422
    assert client.delete("/memories/"+row["id"]).status_code==204
    assert not long_term_references(db,db.get(ChatConversation,"c"),"举例")


def test_explicit_commands_scope_and_deleted_source(api):
    client,db,_=api
    conversation=db.get(ChatConversation,"d")
    assert explicit_command(db,conversation,"记住：先举例再讲算法","r")
    items=client.get("/memories").json();assert len(items)==1 and items[0]["course_id"]=="course"
    assert not long_term_references(db,db.get(ChatConversation,"c"),"算法")
    assert len(long_term_references(db,conversation,"算法"))==1
    assert client.get("/memory-sources/"+items[0]["source_message_id"]).status_code==200
    assert client.get("/memory-sources/missing").status_code==404
    assert explicit_command(db,conversation,"修改记忆：先举例再讲算法 => 先画图再讲算法","r2")
    assert client.get("/memories").json()[0]["content"]=="先画图再讲算法"
    source=db.get(ChatMessage,client.get("/memories").json()[0]["source_message_id"])
    db.delete(source);db.commit()
    assert client.get("/memories").json()==[]


def test_temporary_and_history_controls(api):
    client,db,_=api
    explicit_command(db,db.get(ChatConversation,"c"),"记住：回答尽量简洁","r")
    client.patch("/chat/conversations/c/memory-policy",json={"temporary":True})
    assert not long_term_references(db,db.get(ChatConversation,"c"),"回答")
    assert not recall(db,db.get(ChatConversation,"d"),"回答",100)
    assert explicit_command(db,db.get(ChatConversation,"c"),"记住：喜欢图示","r2")
    assert db.scalar(select(UserMemory).where(UserMemory.content=="喜欢图示")) is None
    # 临时模式仍允许当前会话近期问答，界面明确告知，不伪装成聊天不落盘。
    db.add_all([ChatMessage(conversation_id="c",request_id="normal",position=10,role="user",content="继续讲树遍历"),
        ChatMessage(conversation_id="c",request_id="normal",position=11,role="assistant",content="正在讨论树遍历")]);db.commit()
    assert build_context(db,"c",100)
    assert client.patch("/chat/conversations/v/memory-policy",json={"temporary":True}).status_code==404
    client.patch("/memory-settings",json={"history_enabled":False,"long_term_enabled":False})
    assert not recall(db,db.get(ChatConversation,"d"),"回答",100)
    assert client.post("/memories",json={"content":"喜欢图示"}).status_code==409


def test_source_deletion_cascades_and_controls_type(api):
    client,db,_=api
    explicit_command(db,db.get(ChatConversation,"c"),"全局记住：算法用Python举例","r")
    db.add(ConversationMemorySummary(conversation_id="c",through_position=2,summary_json="[]"));db.commit()
    assert client.patch("/memory-settings",json={"history_enabled":"false","long_term_enabled":True}).status_code==422
    client.patch("/memory-settings",json={"history_enabled":False,"long_term_enabled":True})
    assert db.get(ConversationMemorySummary,"c") is None
    db.delete(db.get(ChatConversation,"c"));db.commit()
    assert client.get("/memories").json()==[]


def test_forgetting_does_not_reintroduce_commands_as_history(api):
    client,db,_=api
    conversation=db.get(ChatConversation,"c")
    explicit_command(db,conversation,"记住：用Python举例","r")
    explicit_command(db,conversation,"忘记：用Python举例","r2")
    assert not long_term_references(db,conversation,"Python")
    assert not recall(db,conversation,"Python",100)
    assert not build_context(db,"c",100)


def test_chat_memory_command_needs_no_model_and_replays_once(api,monkeypatch):
    from unittest.mock import patch
    from app.modules.chat.sending import send_message
    client,db,_=api
    with patch("app.modules.chat.sending.resolve_turn_intent") as planning,patch("app.modules.chat.sending.run_agent") as agent:
        first=send_message(db,"c","u","记住：喜欢用图解释","command-id")
        second=send_message(db,"c","u","记住：喜欢用图解释","command-id")
        assert len(first["messages"])==len(second["messages"])==2
        assert len(client.get("/memories").json())==1
        planning.assert_not_called();agent.assert_not_called()

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from app.core.db import Base
from app.shared.models import User, Course, Lesson, ChatConversation, ChatMessage, now_utc
from app.modules.memory.recall import recall


@pytest.fixture
def db():
    engine=create_engine("sqlite://")
    @event.listens_for(engine,"connect")
    def fk(conn,_): conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id="u",username="u",password_hash="x"),User(id="v",username="v",password_hash="x")]);db.flush()
        db.add_all([Course(id="c",owner_id="u",name="树"),Course(id="d",owner_id="u",name="图")]);db.flush()
        db.add(Lesson(id="l",course_id="c",title="第一课"));db.flush()
        for identity,user,course,lesson in [("global","u",None,None),("course","u","c",None),("lesson","u",None,"l"),("other-course","u","d",None),("other-user","v",None,None)]:
            db.add(ChatConversation(id=identity,user_id=user,course_id=course,lesson_id=lesson,title=identity));db.flush()
            db.add(ChatMessage(id=identity+"m",conversation_id=identity,request_id=identity,position=0,role="user",content="讨论树遍历"))
        db.commit();yield db


def test_scope_and_user_filters(db):
    assert {r["conversation_id"] for r in recall(db,db.get(ChatConversation,"course"),"树遍历",2,budget=5000)}=={"course","lesson"}
    assert {r["conversation_id"] for r in recall(db,db.get(ChatConversation,"lesson"),"树遍历",2,budget=5000)}=={"lesson"}
    assert "other-user" not in {r["conversation_id"] for r in recall(db,db.get(ChatConversation,"global"),"树遍历",2,budget=5000)}


def test_deleted_sources_and_sensitive_messages(db):
    db.get(Course,"c").deleted_at=now_utc()
    db.get(ChatMessage,"other-coursem").content="密码abc，讨论树遍历"
    db.commit()
    rows=recall(db,db.get(ChatConversation,"global"),"树遍历",2,budget=5000)
    assert {r["conversation_id"] for r in rows}=={"global"}
    db.delete(db.get(ChatMessage,"globalm"));db.commit()
    assert not recall(db,db.get(ChatConversation,"global"),"树遍历",2)


def test_before_position_and_no_match(db):
    assert not recall(db,db.get(ChatConversation,"lesson"),"树遍历",0)
    assert not recall(db,db.get(ChatConversation,"global"),"totallyunrelated",2)


def test_vector_failure_keeps_keyword_results(db,monkeypatch):
    import app.modules.memory.recall as module
    monkeypatch.setattr(module,"embed",lambda *a,**k: (_ for _ in ()).throw(RuntimeError("unavailable")))
    monkeypatch.setattr(db.get_bind().dialect,"name","postgresql")
    rows=recall(db,db.get(ChatConversation,"course"),"树遍历",2,budget=5000)
    assert {r["conversation_id"] for r in rows}=={"course","lesson"}

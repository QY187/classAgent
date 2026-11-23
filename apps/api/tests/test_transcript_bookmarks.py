from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.deps import get_current_user
from app.modules.lessons.controller import router
from app.modules.lessons.mapper import clear_transcript
from app.shared.models import Course, Lesson, TranscriptBookmark, TranscriptSegment, User


@pytest.fixture
def bookmark_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        owner = User(id="owner", username="owner", password_hash="test")
        other = User(id="other", username="other", password_hash="test")
        course = Course(id="course", owner_id=owner.id, name="课程")
        lesson = Lesson(id="lesson", course=course, title="课堂")
        second = Lesson(id="another-lesson", course=course, title="另一堂课")
        db.add_all([owner, other])
        db.flush()
        db.add_all([
            TranscriptSegment(id="first", lesson=lesson, start_ms=0, end_ms=2000, text="前一段"),
            TranscriptSegment(id="later", lesson=lesson, start_ms=2000, end_ms=3000, text="后一段"),
            TranscriptSegment(id="other-segment", lesson=second, start_ms=0, end_ms=500, text="另一堂课"),
        ])
        db.commit()

    def database():
        with Session(engine) as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides.update({get_db: database, get_current_user: lambda: "owner"})
    with TestClient(app) as client:
        yield client, app, engine
    engine.dispose()


def test_bookmarks_can_coexist_and_writes_are_idempotent(bookmark_api):
    client, _, _ = bookmark_api
    path = "/lessons/lesson/transcript/first/bookmarks"
    listing = "/lessons/lesson/transcript/bookmarks"
    assert client.get(listing).json() == []
    assert client.put(f"{path}/favorite").status_code == 204
    assert client.put(f"{path}/favorite").status_code == 204
    assert client.put(f"{path}/question").status_code == 204
    assert client.get(listing).json() == [
        {"segment_id": "first", "kind": "favorite"},
        {"segment_id": "first", "kind": "question"},
    ]
    assert client.delete(f"{path}/favorite").status_code == 204
    assert client.delete(f"{path}/favorite").status_code == 204
    assert client.get(listing).json() == [{"segment_id": "first", "kind": "question"}]
    assert client.put(f"{path}/unknown").status_code == 422


def test_bookmarks_check_course_owner_and_segment_lesson(bookmark_api):
    client, app, _ = bookmark_api
    assert client.put("/lessons/lesson/transcript/other-segment/bookmarks/favorite").status_code == 404
    assert client.put("/lessons/lesson/transcript/first/bookmarks/favorite").status_code == 204
    app.dependency_overrides[get_current_user] = lambda: "other"
    assert client.get("/lessons/lesson/transcript/bookmarks").status_code == 404
    assert client.put("/lessons/lesson/transcript/first/bookmarks/question").status_code == 404
    assert client.delete("/lessons/lesson/transcript/first/bookmarks/favorite").status_code == 404


def test_merge_keeps_bookmark_kinds_and_replacing_transcript_clears_them(bookmark_api):
    client, _, engine = bookmark_api
    base = "/lessons/lesson/transcript"
    assert client.put(f"{base}/first/bookmarks/favorite").status_code == 204
    assert client.put(f"{base}/later/bookmarks/favorite").status_code == 204
    assert client.put(f"{base}/later/bookmarks/question").status_code == 204
    with patch("app.infrastructure.tasks.reindex_lesson.delay", side_effect=OperationalError("broker unavailable")):
        merged = client.post(f"{base}/merge", json={"first_id": "first", "second_id": "later"})
    assert merged.status_code == 200
    assert merged.json()["text"] == "前一段后一段"
    assert client.get(f"{base}/bookmarks").json() == [
        {"segment_id": "first", "kind": "favorite"},
        {"segment_id": "first", "kind": "question"},
    ]
    with Session(engine) as db:
        clear_transcript(db, "lesson")
        db.commit()
        assert list(db.scalars(select(TranscriptBookmark))) == []
    assert client.get(f"{base}/bookmarks").json() == []

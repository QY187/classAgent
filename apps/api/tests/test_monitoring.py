"""真实数据库落库、HTTP 鉴权、指标口径和存量权限迁移。模型响应单独隔离。"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telemetry
from app.core.db import Base, get_db
from app.core.passwords import hash_password
from app.core.security import create_access_token
from app.modules.auth.controller import router as auth_router
from app.modules.monitoring.controller import router
from app.modules.monitoring.models import AgentTrace
from app.modules.monitoring.persistence import trace_writer
from app.modules.monitoring.tool_index import TraceTool
from app.shared.models import User


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([User(id="a", username="administrator", password_hash="x", role="admin"),
                    User(id="u", username="owner", password_hash="x"),
                    User(id="v", username="other", password_hash="x")])
        db.commit()
    monkeypatch.setattr(telemetry, "_sink", trace_writer(sessions))
    app = FastAPI()
    app.include_router(router)
    app.include_router(auth_router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield sessions, client
    engine.dispose()


def headers(user="a"):
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def record(request="r", owner="u", conversation="c", *, error=False, cancel=False):
    with telemetry.request_trace(request, conversation) as state:
        telemetry.bind_request(user_id=owner, outcome="cancelled" if cancel else "answered")
        with telemetry.span("model.chat", kind="model", model="test-model", provider="fixture"):
            telemetry.record_usage({"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
        with telemetry.span("tool.execute", kind="tool", tool="list_courses"):
            pass
        if error:
            raise HTTPException(502, "private-exception")
    return state.trace_id


def test_finished_records_survive_new_sessions_and_preserve_tree(setup):
    sessions, client = setup
    trace_id = record()
    with sessions() as db:
        row = db.get(AgentTrace, trace_id)
        assert row.user_id == "u" and row.finished_at is not None
        assert row.metrics["total_tokens"] == 10
        assert row.metrics["db_queries"] == 0  # 观测落库不污染业务 SQL。
        assert list(db.scalars(select(TraceTool.tool))) == ["list_courses"]
    result = client.get(f"/monitoring/traces/{trace_id}", headers=headers()).json()
    events = result["events"]
    root = next(e for e in events if e.get("name") == "request")
    model = next(e for e in events if e.get("name") == "model.chat")
    assert model["parent_span_id"] == root["span_id"]
    assert events[-1]["event"] == "request.finished"


def test_started_request_is_visible_and_long_running_is_not_failed(setup):
    sessions, client = setup
    with telemetry.request_trace("live", "c") as state:
        response = client.get(f"/monitoring/traces/{state.trace_id}", headers=headers()).json()
        assert response["status"] == "running" and response["finished_at"] is None
    with sessions() as db:
        db.add(AgentTrace(trace_id="old", request_id="stale", conversation_id="c", status="running",
                          started_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
    result = client.get("/monitoring/traces?status=incomplete", headers=headers()).json()
    assert [row["trace_id"] for row in result["items"]] == ["old"]
    assert result["items"][0]["status"] == "incomplete"


@pytest.mark.parametrize("path", ["/overview", "/tools", "/traces", "/traces/secret"])
def test_admin_queries_require_authenticated_server_role(setup, path):
    _, client = setup
    assert client.get("/monitoring" + path).status_code == 401
    assert client.get("/monitoring" + path, headers=headers("u")).status_code == 403
    assert client.get("/monitoring" + path, headers={"Authorization": "Bearer forged"}).status_code == 401


def test_own_detail_cannot_leak_other_users_even_with_same_request_id(setup):
    _, client = setup
    mine = record("shared", "u", "mine")
    theirs = record("shared", "v", "theirs")
    result = client.get("/monitoring/requests/shared", headers=headers("u")).json()
    assert [item["trace_id"] for item in result["items"]] == [mine]
    assert theirs not in str(result)
    assert client.get("/monitoring/requests/shared?conversation_id=theirs", headers=headers("u")).status_code == 404
    assert client.get("/monitoring/requests/shared", headers=headers("a")).status_code == 404
    assert client.get("/monitoring/requests/shared").status_code == 401


def test_own_attempts_do_not_cross_conversations_and_retries_have_unique_trace_ids(setup):
    _, client = setup
    first = record("retry", conversation="one")
    second = record("retry", conversation="one")
    record("retry", conversation="two")
    result = client.get("/monitoring/requests/retry?conversation_id=one", headers=headers("u")).json()
    assert [row["trace_id"] for row in result["items"]] == [second, first]


def test_overview_denominators_missing_usage_and_nearest_rank(setup):
    sessions, client = setup
    first = record("one")
    second = record("two", cancel=True)
    with pytest.raises(HTTPException):
        record("three", error=True)
    with telemetry.request_trace("four", "c"):
        with telemetry.span("model.embedding", kind="model"):
            telemetry.record_usage({"prompt_tokens": 11})
        with telemetry.span("model.chat", kind="model"):
            pass
    with sessions() as db:
        rows = list(db.scalars(select(AgentTrace).order_by(AgentTrace.started_at)))
        for index, row in enumerate(rows, 1):
            row.duration_ms = index * 100
        db.add(AgentTrace(trace_id="never-finished", request_id="pending", conversation_id="c", status="running",
                          started_at=datetime.now(timezone.utc), metrics={"total_tokens": 99999}))
        db.commit()
    result = client.get("/monitoring/overview", headers=headers()).json()
    assert (result["total"], result["finished"], result["ok"], result["error"], result["cancelled"], result["running"]) == (5, 4, 2, 1, 1, 1)
    assert result["normal_return_rate"] == .5
    assert (result["p50_ms"], result["p95_ms"]) == (200, 400)
    assert result["metrics"]["total_tokens"] == 30
    assert result["metrics"]["prompt_tokens"] == 32
    assert result["metrics"]["model_calls"] == 5
    assert result["metrics"]["usage_reported_calls"] == 4
    assert result["metrics"]["total_tokens_reported_calls"] == 3
    assert result["metrics"]["usage_missing_calls"] == 1
    assert result["outcomes"]["cancelled"] == 1


def test_empty_overview_has_null_percentiles_and_no_invented_success(setup):
    _, client = setup
    result = client.get("/monitoring/overview", headers=headers()).json()
    assert result["total"] == 0 and result["p50_ms"] is None and result["normal_return_rate"] is None


def test_pagination_filters_and_summary_use_same_scope(setup):
    _, client = setup
    record("one")
    record("two")
    result = client.get("/monitoring/traces?page_size=1&page=1", headers=headers()).json()
    other = client.get("/monitoring/traces?page_size=1&page=2", headers=headers()).json()
    assert result["total"] == 2 and result["items"][0]["request_id"] == "two"
    assert other["items"][0]["request_id"] == "one"
    assert "events" not in result["items"][0]
    assert client.get("/monitoring/traces?request_id=one", headers=headers()).json()["total"] == 1
    assert client.get("/monitoring/overview?request_id=one", headers=headers()).json()["total"] == 1
    assert client.get("/monitoring/traces?tool=list_courses", headers=headers()).json()["total"] == 2
    assert client.get("/monitoring/traces?tool=missing", headers=headers()).json()["total"] == 0
    assert client.get("/monitoring/tools", headers=headers()).json() == ["list_courses"]
    assert client.get("/monitoring/traces?status=error", headers=headers()).json()["total"] == 0


@pytest.mark.parametrize("query", ["page=0", "page_size=101", "status=oops", "since=2026-01-01T00:00:00",
                                   "since=2026-01-01T00:00:00Z&until=2026-12-01T00:00:00Z",
                                   "since=2026-01-03T00:00:00Z&until=2026-01-02T00:00:00Z"])
def test_invalid_filters_are_rejected(setup, query):
    _, client = setup
    assert client.get("/monitoring/traces?" + query, headers=headers()).status_code == 422


def test_persistence_failure_does_not_change_business_result_or_exception(setup, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-database-url")
    monkeypatch.setattr(telemetry, "_sink", fail)
    record()
    with pytest.raises(HTTPException) as caught:
        record(error=True)
    assert caught.value.status_code == 502
    assert telemetry.current_trace() is None


def test_event_buffer_is_bounded_and_aggregate_remains_complete(setup):
    sessions, _ = setup
    with telemetry.request_trace("many", "c") as state:
        for _ in range(600):
            telemetry.trace_event("agent.repair", reason="invalid_final", answer="private-answer", api_key="private-key")
        with telemetry.span("tool.execute", kind="tool", tool="list_courses"):
            pass
    with sessions() as db:
        row = db.get(AgentTrace, state.trace_id)
        assert len(row.events) <= telemetry.MAX_TRACE_EVENTS + 1
        assert row.events[-1]["event"] == "request.finished"
        assert row.metrics["repair_count"] == 600 and row.dropped_events > 0
        assert "private" not in str(row.events)
        assert list(db.scalars(select(TraceTool.tool))) == ["list_courses"]


def test_me_returns_database_role_and_register_cannot_choose_admin(setup):
    _, client = setup
    assert client.get("/auth/me", headers=headers()).json()["role"] == "admin"
    assert client.get("/auth/me", headers=headers("u")).json()["role"] == "user"
    with patch("app.modules.auth.controller.get_settings", return_value=SimpleNamespace(allow_registration=True)):
        response = client.post("/auth/register", json={"username": "new-user", "password": "test-password", "role": "admin"})
    assert response.status_code == 201 and response.json()["role"] == "user"


def test_role_migration_is_idempotent_and_does_not_trust_username_alone(tmp_path):
    import app.main as main
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username VARCHAR(100), password_hash VARCHAR(200), avatar_content_type VARCHAR(32), created_at DATETIME)"))
        connection.execute(text("INSERT INTO users (id, username, password_hash) VALUES ('a', 'bootstrap-admin', :password)"),
                           {"password": hash_password("changed-password")})
    settings = SimpleNamespace(admin_username="bootstrap-admin", admin_password="bootstrap-password")
    with patch.object(main, "engine", engine), patch.object(main, "SessionLocal", sessionmaker(bind=engine)), patch.object(main, "get_settings", return_value=settings):
        assert main._prepare_user_role_column() is True
        assert main._prepare_user_role_column() is False
        main._seed_root_user(bootstrap_roles=True)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT role FROM users")) == "user"
        with engine.begin() as connection:
            connection.execute(text("UPDATE users SET password_hash=:password"), {"password": hash_password("bootstrap-password")})
        main._seed_root_user(bootstrap_roles=True)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT role FROM users")) == "admin"
    engine.dispose()


def test_real_message_boundary_persists_result_and_replay_without_new_model(setup):
    sessions, client = setup
    from app.modules.chat.conversations import create_global_conversation
    from app.modules.chat.intent_schema import IntentPayload, TurnDecision
    from app.modules.chat.sending import send_message
    with sessions() as db:
        chat = create_global_conversation(db, "owner")
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=TurnDecision(relation="new", intent=IntentPayload())), patch(
            "app.modules.chat.sending.run_agent", return_value={"answer": "测试回答", "citations": [], "outcome": "answered"}
        ) as model:
            send_message(db, chat["id"], "owner", "查询课程", "live-request")
            send_message(db, chat["id"], "owner", "查询课程", "live-request")
        assert model.call_count == 1
    rows = client.get("/monitoring/requests/live-request", headers=headers("u")).json()["items"]
    assert len(rows) == 2 and {row["outcome"] for row in rows} == {"answered", "replayed"}
    assert all(row["events"][-1]["event"] == "request.finished" for row in rows)

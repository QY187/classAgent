"""真实账本及 HTTP 集成；仅模拟供应商网络边界，不调用真实付费 API。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.config import AgentModelConfig, get_settings
from app.core.db import Base, get_db
from app.core.chat_failures import ChatRequestFailure
from app.core.model_budget import input_reservation, quota_chat_post, quota_user
from app.core.security import create_access_token
from app.modules.agent.completion import complete
from app.modules.chat.controller import router as chat_router
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.sending import send_message
from app.modules.quotas.controller import router
from app.modules.quotas.models import DailyTokenUsage, TokenUsageEntry
from app.modules.quotas import service
from app.shared.models import User


BODY = {"model": "fixture-model", "messages": [{"role": "user", "content": "问题"}], "max_tokens": 100}


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "token_quota_enabled", True)
    monkeypatch.setattr(settings, "daily_token_limit", 100000)
    engine = create_engine("sqlite:///" + str(tmp_path / "quota.db"), connect_args={"check_same_thread": False, "timeout": 15})
    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([User(id="u", username="owner", password_hash="x"), User(id="v", username="other", password_hash="x"),
                    User(id="a", username="admin", password_hash="x", role="admin")]); db.commit()
    app = FastAPI(); app.include_router(router); app.include_router(chat_router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(sessions=sessions, client=client, engine=engine,
            headers=lambda user="u": {"Authorization": "Bearer " + create_access_token(user)})
    engine.dispose()


def view(env, user="u", now=None):
    with env.sessions() as db:
        return service.snapshot(db, user, now=now)


def call(env, post, *, user="u"):
    with env.sessions() as db, quota_user(db, user):
        return quota_chat_post(post, "https://provider.invalid", headers={}, json=BODY, timeout=1)


def response(usage=None, *, status=200, content="{}"):
    return httpx.Response(status, json={"usage": usage, "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]},
                          request=httpx.Request("POST", "https://provider.invalid"))


@pytest.mark.parametrize("provider", ["deepseek", "dashscope", "openai_compatible"])
def test_agent_provider_uses_real_ledger_and_selected_model(env, provider):
    settings = SimpleNamespace(agent_provider=provider, agent_base_url="https://provider.invalid/v1",
        agent_api_key="agent-fixture", agent_model="selected-agent-model",
        deepseek_api_key="unused-legacy", summary_model="legacy-model", dashscope_api_key="unused-dashscope")
    upstream = Mock(return_value=response({"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20},
                                         content="模型回答"))
    with env.sessions() as db, quota_user(db, "u"), patch(
            "app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.httpx.post", upstream):
        assert complete([{"role": "user", "content": "问题"}], [], 2)["content"] == "模型回答"
    assert view(env)["used_tokens"] == 20 and view(env)["reserved_tokens"] == 0
    assert view(env, "v")["used_tokens"] == 0
    with env.sessions() as db:
        entry = db.scalar(select(TokenUsageEntry).where(TokenUsageEntry.user_id == "u"))
        assert entry.model == "selected-agent-model" and entry.purpose == "chat"
    with env.sessions() as db:
        service.change_limit(db, "u", 20, "a")
    with env.sessions() as db, quota_user(db, "u"), patch(
            "app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.httpx.post") as blocked, pytest.raises(ChatRequestFailure) as caught:
        complete([], [], 2)
    assert caught.value.failure.code == "quota_exhausted"
    blocked.assert_not_called()


def test_user_selected_model_is_billed_and_replay_or_changed_selection_does_not_charge(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_models", [AgentModelConfig(id="paid", label="可选模型",
        provider="openai_compatible", model="selected-paid-model", base_url="https://provider.invalid/v1", api_key="fixture")])
    with env.sessions() as db:
        chat = create_global_conversation(db, "owner")
    plan = json.dumps({"relation": "new", "intent": {}})
    upstream = Mock(return_value=response({"total_tokens": 20}, content=plan))
    with env.sessions() as db, patch("app.modules.agent.completion.httpx.post", upstream), patch(
            "app.modules.chat.sending.run_agent", return_value={"answer": "已查询", "citations": []}):
        send_message(db, chat["id"], "owner", "查询课程", "selected", model_id="paid")
        send_message(db, chat["id"], "owner", "查询课程", "selected", model_id="paid")
        with pytest.raises(HTTPException) as changed:
            send_message(db, chat["id"], "owner", "查询课程", "selected", model_id="default")
        assert changed.value.status_code == 409
    assert upstream.call_count == 1 and view(env)["used_tokens"] == 20 and view(env)["reserved_tokens"] == 0
    with env.sessions() as db:
        assert db.scalar(select(TokenUsageEntry.model).where(TokenUsageEntry.user_id == "u")) == "selected-paid-model"


def test_default_limit_and_independent_users(env):
    assert view(env)["daily_limit"] == 100000
    entry = service.reserve(env.sessions, "u", 600, model="fixture", purpose="test")
    assert view(env)["remaining_tokens"] == 99400 and view(env, "v")["remaining_tokens"] == 100000
    assert service.settle(env.sessions, entry, 50, input_tokens=30, output_tokens=20)
    assert view(env)["used_tokens"] == 50 and view(env)["reserved_tokens"] == 0
    assert not service.settle(env.sessions, entry, 50)
    assert view(env)["used_tokens"] == 50


def test_daily_boundary_uses_shanghai_and_late_settlement_keeps_original_day(env):
    before = datetime(2026, 11, 1, 15, 59, 59, tzinfo=timezone.utc)
    after = before + timedelta(seconds=1)
    entry = service.reserve(env.sessions, "u", 300, model="fixture", purpose="test", now=before)
    assert view(env, now=before)["day"] == "2026-11-01"
    assert view(env, now=after)["day"] == "2026-11-02"
    assert view(env, now=after)["remaining_tokens"] == 100000
    service.settle(env.sessions, entry, 100)
    assert view(env, now=before)["used_tokens"] == 100 and view(env, now=after)["used_tokens"] == 0


def test_atomic_concurrent_reservations_never_exceed_limit(env):
    with env.sessions() as db:
        service.change_limit(db, "u", 1000, "a")
    def reserve(_):
        try:
            return service.reserve(env.sessions, "u", 300, model="fixture", purpose="concurrency")
        except ChatRequestFailure as exc:
            assert exc.failure.code == "quota_exhausted"
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(reserve, range(12)))
    assert len([item for item in ids if item]) == 3
    assert view(env)["reserved_tokens"] == 900


def test_limit_changes_do_not_reset_spend_and_zero_disables_calls(env):
    entry = service.reserve(env.sessions, "u", 500, model="fixture", purpose="test")
    service.settle(env.sessions, entry, 200)
    with env.sessions() as db:
        service.change_limit(db, "u", 0, "a")
    post = Mock()
    with pytest.raises(ChatRequestFailure) as caught:
        call(env, post)
    assert caught.value.failure.code == "quota_exhausted" and not post.called
    with env.sessions() as db:
        service.change_limit(db, "u", None, "a")
    assert view(env)["used_tokens"] == 200 and view(env)["remaining_tokens"] == 99800


def test_success_uses_actual_provider_usage_and_sets_output_limit(env):
    post = Mock(return_value=response({"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20}))
    call(env, post)
    assert view(env)["used_tokens"] == 20 and view(env)["reserved_tokens"] == 0
    assert post.call_args.kwargs["json"]["max_tokens"] == 100


@pytest.mark.parametrize("usage", [{"prompt_tokens": 13, "completion_tokens": 7}, {"total_tokens": 20},
                                  {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 1}])
def test_partial_or_inconsistent_usage_does_not_undercount_known_tokens(env, usage):
    call(env, Mock(return_value=response(usage)))
    assert view(env)["used_tokens"] == 20


@pytest.mark.parametrize("usage", [None, {}, {"total_tokens": -1}, {"total_tokens": True}])
def test_missing_or_invalid_usage_keeps_reservation_for_reconciliation(env, usage):
    call(env, Mock(return_value=response(usage)))
    assert view(env)["reserved_tokens"] == input_reservation(BODY) + 100
    with env.sessions() as db:
        assert db.scalar(select(TokenUsageEntry)).status == "uncertain"


@pytest.mark.parametrize("error,held", [(httpx.ReadTimeout("private"), True), (httpx.ConnectError("private"), False)])
def test_transport_uncertainty_is_not_refunded_as_zero(env, error, held):
    with pytest.raises(type(error)):
        call(env, Mock(side_effect=error))
    assert bool(view(env)["reserved_tokens"]) == held


def test_provider_rejection_releases_reservation(env):
    call(env, Mock(return_value=response(status=429)))
    assert view(env)["reserved_tokens"] == 0 and view(env)["used_tokens"] == 0


def test_billing_store_outage_blocks_provider_without_exposing_internal_details(env):
    post = Mock()
    with patch("app.modules.quotas.service.reserve", side_effect=OperationalError("PRIVATE_SQL", {}, RuntimeError("PRIVATE_DB"))), pytest.raises(ChatRequestFailure) as caught:
        call(env, post)
    assert caught.value.failure.code == "quota_storage_unavailable" and "PRIVATE" not in caught.value.detail and not post.called


def test_unbound_model_call_is_blocked(env):
    post = Mock()
    with pytest.raises(ChatRequestFailure) as caught:
        quota_chat_post(post, "https://provider.invalid", headers={}, json=BODY, timeout=1)
    assert caught.value.failure.code == "quota_identity_required" and not post.called


def test_api_permissions_validation_and_user_isolation(env):
    client = env.client
    assert client.get("/quotas/me").status_code == 401
    assert client.get("/quotas/admin/users", headers=env.headers()).status_code == 403
    assert client.put("/quotas/admin/users/v", headers=env.headers(), json={"daily_limit": 0}).status_code == 403
    assert client.put("/quotas/admin/users/u", headers=env.headers("a"), json={"daily_limit": 1234}).status_code == 200
    assert client.get("/quotas/me", headers=env.headers()).json()["daily_limit"] == 1234
    assert client.get("/quotas/me", headers=env.headers("v")).json()["daily_limit"] == 100000
    for invalid in [-1, True, "100", 1000000001]:
        assert client.put("/quotas/admin/users/u", headers=env.headers("a"), json={"daily_limit": invalid}).status_code == 422
    assert client.put("/quotas/admin/users/u", headers=env.headers("a"), json={"daily_limit": 1, "user_id": "v"}).status_code == 422


def test_admin_reconciles_uncertain_usage_once_and_cannot_reconcile_active_call(env):
    call(env, Mock(return_value=response()))
    with env.sessions() as db:
        entry = db.scalar(select(TokenUsageEntry)).id
    endpoint = f"/quotas/admin/entries/{entry}/resolve"
    assert env.client.put(endpoint, headers=env.headers(), json={"actual_tokens": 50}).status_code == 403
    assert env.client.put(endpoint, headers=env.headers("a"), json={"actual_tokens": 50}).status_code == 200
    assert env.client.put(endpoint, headers=env.headers("a"), json={"actual_tokens": 50}).status_code == 409
    assert view(env)["used_tokens"] == 50 and view(env)["reserved_tokens"] == 0
    active = service.reserve(env.sessions, "u", 100, model="fixture", purpose="test")
    assert env.client.put(f"/quotas/admin/entries/{active}/resolve", headers=env.headers("a"), json={"actual_tokens": 0}).status_code == 409
    assert env.client.get("/quotas/me/entries", headers=env.headers("v")).json()["total"] == 0


def test_real_chat_sse_quota_failure_is_saved_and_provider_is_not_called(env):
    with env.sessions() as db:
        chat = create_global_conversation(db, "owner")
        service.change_limit(db, "u", 0, "a")
    with patch("app.modules.chat.streaming.SessionLocal", env.sessions), patch(
        "app.modules.agent.completion.get_settings", return_value=SimpleNamespace(deepseek_api_key="fixture", summary_model="fixture")), patch(
        "app.modules.agent.completion.httpx.post") as post:
        result = env.client.post(f"/chat/conversations/{chat['id']}/ask/stream", headers=env.headers(),
            json={"request_id": str(uuid4()), "content": "查询我的课程"})
    assert "quota_exhausted" in result.text and "event: done" not in result.text and not post.called
    saved = env.client.get(f"/chat/conversations/{chat['id']}/messages", headers=env.headers()).json()
    assert saved["messages"][0]["status"] == "failed" and "额度不足" in saved["messages"][0]["error_message"]


def test_chat_replay_does_not_charge_again(env):
    with env.sessions() as db:
        chat = create_global_conversation(db, "owner")
    plan = json.dumps({"relation": "new", "intent": {}})
    provider = Mock(return_value=response({"total_tokens": 20}, content=plan))
    with env.sessions() as db, patch("app.modules.agent.completion.get_settings", return_value=SimpleNamespace(deepseek_api_key="fixture", summary_model="fixture")), patch(
        "app.modules.agent.completion.httpx.post", provider), patch("app.modules.chat.sending.run_agent", return_value={"answer": "已查询", "citations": []}):
        send_message(db, chat["id"], "owner", "查询课程", "replay")
        send_message(db, chat["id"], "owner", "查询课程", "replay")
    assert provider.call_count == 1 and view(env)["used_tokens"] == 20


def test_invalid_model_result_still_counts_reported_usage(env):
    with env.sessions() as db, quota_user(db, "u"), patch("app.modules.agent.completion.get_settings", return_value=SimpleNamespace(deepseek_api_key="fixture", summary_model="fixture")), patch(
        "app.modules.agent.completion.httpx.post", return_value=httpx.Response(200, json={"usage": {"total_tokens": 70}}, request=httpx.Request("POST", "https://provider.invalid"))), pytest.raises(ChatRequestFailure):
        complete([], [], 1)
    assert view(env)["used_tokens"] == 70


def test_provider_timeout_status_is_uncertain_even_without_transport_exception(env):
    call(env, Mock(return_value=response(status=408)))
    assert view(env)["reserved_tokens"] > 0


def test_total_below_known_input_without_output_cannot_be_treated_as_zero(env):
    call(env, Mock(return_value=response({"prompt_tokens": 80, "total_tokens": 0})))
    assert view(env)["reserved_tokens"] > 0 and view(env)["used_tokens"] == 0


def test_actual_usage_above_conservative_reservation_is_never_discarded(env):
    call(env, Mock(return_value=response({"total_tokens": 150000})))
    assert view(env)["used_tokens"] == 150000 and view(env)["remaining_tokens"] == 0
    with pytest.raises(ChatRequestFailure):
        call(env, Mock())


def test_stream_usage_trailer_settles_even_when_choices_are_empty(env):
    from unittest.mock import MagicMock
    from app.modules.rag.streaming import stream_completion
    transport = MagicMock()
    transport.__enter__.return_value.status_code = 200
    transport.__enter__.return_value.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"content":"{\\\"claims\\\":[]}"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":9,"total_tokens":20}}',
        'data: [DONE]']
    with env.sessions() as db, quota_user(db, "u"), patch("app.modules.rag.streaming.httpx.stream", return_value=transport) as stream:
        raw = stream_completion("https://provider.invalid", {}, BODY, lambda claims: None)
    assert json.loads(raw) == {"claims": []}
    assert stream.call_args.kwargs["json"]["stream_options"] == {"include_usage": True}
    assert view(env)["used_tokens"] == 20 and view(env)["reserved_tokens"] == 0


def test_user_context_is_isolated_across_threads_and_reset_after_call(env):
    def invoke(user):
        call(env, Mock(return_value=response({"total_tokens": 17 if user == "u" else 23})), user=user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(invoke, ["u", "v"]))
    assert view(env)["used_tokens"] == 17 and view(env, "v")["used_tokens"] == 23
    test_unbound_model_call_is_blocked(env)


def test_background_summary_charges_lesson_owner(env):
    from app.infrastructure.tasks import generate_summary
    from app.shared.models import Course, Lesson, LessonSummary, TranscriptSegment
    with env.sessions() as db:
        db.add(Course(id="course", owner_id="v", name="额度课程")); db.flush()
        db.add(Lesson(id="lesson", course_id="course", title="额度课次")); db.flush()
        db.add(TranscriptSegment(id="segment", lesson_id="lesson", start_ms=0, end_ms=1, text="二叉树每个结点最多有两个子结点。")); db.commit()
    with patch("app.core.db.SessionLocal", env.sessions), patch("app.modules.summaries.service.get_settings", return_value=SimpleNamespace(deepseek_api_key="fixture", summary_model="fixture")), patch(
        "app.modules.summaries.service.httpx.post", return_value=response({"total_tokens": 33}, content='{"overview":"课堂纪要"}')), patch("app.infrastructure.tasks.reindex_lesson.delay"):
        generate_summary.run("lesson")
    assert view(env, "v")["used_tokens"] == 33 and view(env)["used_tokens"] == 0
    with env.sessions() as db:
        assert db.scalar(select(LessonSummary)).status == "completed"


def test_direct_quiz_generation_is_billed_even_if_question_validation_fails(env):
    from app.modules.quizzes.service import generate_quiz
    from app.modules.quizzes.schemas import QuizGenerate
    from app.shared.models import Course, Lesson, TranscriptSegment
    with env.sessions() as db:
        db.add(Course(id="course", owner_id="u", name="额度课程")); db.flush()
        db.add(Lesson(id="lesson", course_id="course", title="额度课次")); db.flush()
        db.add_all([TranscriptSegment(id=f"s{i}", lesson_id="lesson", start_ms=i, end_ms=i+1, text="课堂原文") for i in range(3)]); db.commit()
    with env.sessions() as db, patch("app.modules.quizzes.service.get_settings", return_value=SimpleNamespace(deepseek_api_key="fixture", summary_model="fixture")), patch(
        "app.modules.quizzes.service.httpx.post", return_value=response({"total_tokens": 40}, content='{"questions":[]}')), pytest.raises(HTTPException):
        generate_quiz(db, "course", QuizGenerate(count=3), "owner")
    assert view(env)["used_tokens"] == 40

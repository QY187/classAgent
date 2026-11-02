"""失败原因分类、真实消息/SSE 持久化、隐私和重试验证；供应商仅在网络边界模拟。"""
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.chat_failures import ChatRequestFailure, public_failure
from app.core.db import Base, get_db
from app.core.security import create_access_token
from app.modules.agent.completion import complete
from app.modules.chat.controller import router
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.intent_schema import IntentPayload, TurnDecision
from app.modules.chat.messages import read_messages
from app.modules.chat.sending import send_message
from app.shared.models import User

SETTINGS = SimpleNamespace(deepseek_api_key="FAKE_PRIVATE_KEY", summary_model="fixture-model")
PLAN = TurnDecision(relation="new", intent=IntentPayload())


def provider_response(status, payload=None):
    return httpx.Response(status, json=payload or {"error": {"message": "PRIVATE_PROVIDER_RESPONSE"}},
                          request=httpx.Request("POST", "https://provider.invalid/chat"))


@pytest.fixture
def env():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add(User(id="u", username="owner", password_hash="x")); db.commit()
        chat = create_global_conversation(db, "owner")
    app = FastAPI()
    app.include_router(router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(sessions=sessions, client=client, chat=chat["id"],
                              headers={"Authorization": "Bearer " + create_access_token("u")})
    engine.dispose()


@pytest.mark.parametrize("status,code", [
    (401, "model_authentication"), (402, "model_billing"), (403, "model_permission"),
    (408, "model_timeout"), (429, "model_rate_limited"), (500, "model_unavailable"),
    (503, "model_unavailable"), (504, "model_timeout"), (400, "model_request_rejected"),
])
def test_provider_status_is_classified_without_response_or_credentials(status, code):
    with patch("app.modules.agent.completion.get_settings", return_value=SETTINGS), patch(
        "app.modules.agent.completion.httpx.post", return_value=provider_response(status)
    ), pytest.raises(ChatRequestFailure) as caught:
        complete([], [], timeout=1)
    assert caught.value.failure.code == code
    assert "PRIVATE" not in caught.value.detail and "https://" not in caught.value.detail


@pytest.mark.parametrize("error,code", [
    (httpx.ReadTimeout("PRIVATE_TIMEOUT"), "model_timeout"),
    (httpx.ConnectError("PRIVATE_URL_KEY"), "model_connection"),
])
def test_transport_error_uses_type_not_exception_text(error, code):
    with patch("app.modules.agent.completion.get_settings", return_value=SETTINGS), patch(
        "app.modules.agent.completion.httpx.post", side_effect=error
    ), pytest.raises(ChatRequestFailure) as caught:
        complete([], [], timeout=1)
    assert caught.value.failure.code == code and "PRIVATE" not in caught.value.detail


def test_unconfigured_and_malformed_model_are_distinguishable():
    with patch("app.modules.agent.completion.get_settings", return_value=SimpleNamespace(summary_model="fixture", deepseek_api_key="")), pytest.raises(ChatRequestFailure) as missing:
        complete([], [], timeout=1)
    assert missing.value.failure.code == "ai_not_configured"
    with patch("app.modules.agent.completion.get_settings", return_value=SETTINGS), patch(
        "app.modules.agent.completion.httpx.post", return_value=provider_response(200, {"PRIVATE": "payload"})
    ), pytest.raises(ChatRequestFailure) as invalid:
        complete([], [], timeout=1)
    assert invalid.value.failure.code == "invalid_model_response"


@pytest.mark.parametrize("error,code", [
    (RuntimeError("PRIVATE_SECRET"), "internal_error"),
    (OperationalError("PRIVATE_SQL", {"secret": "PRIVATE_PARAM"}, RuntimeError("PRIVATE_DB")), "storage_unavailable"),
    (HTTPException(500, "PRIVATE_BACKEND_ERROR"), "internal_error"),
    (HTTPException(504, "PRIVATE_TIMEOUT"), "request_timeout"),
])
def test_unknown_and_storage_errors_do_not_invent_or_expose_detail(error, code):
    failure = public_failure(error, stage="saving")
    assert failure.code == code and "保存回答阶段失败" in failure.message
    assert "PRIVATE" not in failure.message


def test_planning_failure_survives_history_reload(env):
    with env.sessions() as db, patch("app.modules.chat.sending.resolve_turn_intent", side_effect=ChatRequestFailure("model_rate_limited")):
        with pytest.raises(ChatRequestFailure) as caught:
            send_message(db, env.chat, "owner", "查询课程", "failure")
        assert caught.value.failure.stage == "planning"
    with env.sessions() as fresh:
        history = read_messages(fresh, env.chat, "owner")
        row = history["messages"][0]
        assert row["status"] == "failed" and "理解问题阶段失败" in row["error_message"]
        assert "请求限制" in row["error_message"]
        assert not history["conversation"]["generating"]
        assert len(history["messages"]) == 1


def test_retry_clears_failure_and_does_not_duplicate_question_or_plan(env):
    with env.sessions() as db, patch("app.modules.chat.sending.resolve_turn_intent", return_value=PLAN) as planner, patch(
        "app.modules.chat.sending.run_agent", side_effect=[ChatRequestFailure("round_limit"), {"answer": "正常回答", "citations": []}]
    ):
        with pytest.raises(ChatRequestFailure):
            send_message(db, env.chat, "owner", "查询课程", "retry")
        assert "执行任务阶段失败" in read_messages(db, env.chat, "owner")["messages"][0]["error_message"]
        result = send_message(db, env.chat, "owner", "查询课程", "retry")
        assert len(result["messages"]) == 2 and planner.call_count == 1
        assert all(item["status"] == "completed" and item["error_message"] is None for item in result["messages"])


def test_failure_record_write_error_does_not_replace_original_reason(env):
    with env.sessions() as db, patch("app.modules.chat.sending.resolve_turn_intent", side_effect=ChatRequestFailure("model_timeout")), patch(
        "app.modules.chat.sending._finish_failed", side_effect=OperationalError("PRIVATE_SQL", {}, RuntimeError("PRIVATE_DB"))
    ), pytest.raises(ChatRequestFailure) as caught:
        send_message(db, env.chat, "owner", "查询课程", "storage-down")
    assert caught.value.failure.code == "model_timeout" and "AI 服务未在规定时间内响应" in caught.value.detail
    assert "PRIVATE" not in caught.value.detail


def test_real_http_sse_reports_same_reason_as_saved_history(env):
    request_id = str(uuid4())
    with patch("app.modules.chat.streaming.SessionLocal", env.sessions), patch(
        "app.modules.agent.completion.get_settings", return_value=SETTINGS
    ), patch("app.modules.agent.completion.httpx.post", return_value=provider_response(429)):
        response = env.client.post(f"/chat/conversations/{env.chat}/ask/stream", headers=env.headers,
                                   json={"content": "查询课程", "request_id": request_id})
    assert response.status_code == 200 and "event: error" in response.text and "event: done" not in response.text
    last = response.text.strip().split("\n\n")[-1]
    failure = json.loads(last.split("data: ", 1)[1])
    assert failure["error_code"] == "model_rate_limited" and failure["stage"] == "planning"
    assert failure["request_id"] == request_id and "PRIVATE" not in response.text
    history = env.client.get(f"/chat/conversations/{env.chat}/messages", headers=env.headers).json()
    assert history["messages"][0]["error_message"] == failure["detail"]
    assert history["messages"][0]["status"] == "failed"


def test_non_streaming_failure_also_has_safe_specific_reason(env):
    with patch("app.modules.agent.completion.get_settings", return_value=SETTINGS), patch(
        "app.modules.agent.completion.httpx.post", return_value=provider_response(401)
    ):
        response = env.client.post(f"/chat/conversations/{env.chat}/ask", headers=env.headers,
                                   json={"content": "查询课程", "request_id": str(uuid4())})
    assert response.status_code == 503 and "认证失败" in response.json()["detail"]
    assert "PRIVATE" not in response.text

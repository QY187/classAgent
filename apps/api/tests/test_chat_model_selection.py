"""模型目录、请求注入、持久化、隔离与 HTTP/SSE；仅模拟供应商网络。"""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import AgentModelConfig, Settings, get_settings
from app.core.db import Base, get_db
from app.core.security import create_access_token
from app.modules.agent.completion import complete
from app.modules.agent.model_selection import active_chat_model, bind_chat_model, chat_model_scope, model_catalog, select_chat_model
from app.modules.chat.cancellation import stop_generation
from app.modules.chat.controller import router
from app.modules.chat.conversations import create_conversation, create_global_conversation
from app.modules.chat.messages import read_messages
from app.modules.chat.migrations import prepare_chat_model_selection
from app.modules.chat.sending import send_message
from app.shared.models import ChatConversation, ChatMessage, Course, Lesson, TranscriptSegment, User, now_utc


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = get_settings()
    for key, value in {"agent_provider": "deepseek", "agent_base_url": "", "agent_api_key": "",
                       "agent_model": "", "deepseek_api_key": "legacy-private-key",
                       "summary_model": "legacy-model", "dashscope_api_key": "dashscope-private-key"}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(settings, "agent_models", [AgentModelConfig(id=name, label=label,
        provider="openai_compatible", model=f"model-{name}", base_url=f"https://{name}.invalid/v1",
        api_key=f"private-key-{name}") for name, label in (("alpha", "模型甲"), ("beta", "模型乙"))])
    engine = create_engine("sqlite:///" + str(tmp_path / "selection.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.modules.chat.streaming.SessionLocal", sessions)
    with sessions() as db:
        db.add_all([User(id="u", username="owner", password_hash="x"), User(id="v", username="other", password_hash="x")]); db.flush()
        db.add(Course(id="c", name="数据结构", owner_id="u")); db.flush()
        db.add(Lesson(id="l", title="二叉树", course_id="c")); db.flush()
        db.add(TranscriptSegment(id="s", lesson_id="l", start_ms=1000, end_ms=2000,
                                 speaker="老师", text="二叉树最多两个孩子。")); db.commit()
    app = FastAPI(); app.include_router(router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield SimpleNamespace(settings=settings, sessions=sessions, engine=engine, client=client,
            headers={"Authorization": "Bearer " + create_access_token("u")},
            other={"Authorization": "Bearer " + create_access_token("v")})
    engine.dispose()


def response(value, *, calls=None):
    message = {"role": "assistant", "content": json.dumps(value, ensure_ascii=False) if value is not None else None}
    if calls:
        message["tool_calls"] = calls
    return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls" if calls else "stop", "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        request=httpx.Request("POST", "https://fixture.invalid"))


def chat(env, scoped=False):
    with env.sessions() as db:
        return (create_conversation(db, "l", "owner") if scoped else create_global_conversation(db, "owner"))["id"]


def test_catalog_requires_login_and_exposes_no_secrets_or_endpoints(env):
    assert env.client.get("/chat/models").status_code == 401
    result = env.client.get("/chat/models", headers=env.headers)
    assert result.status_code == 200
    data = result.json()
    assert [item["id"] for item in data["items"]] == ["default", "dashscope", "alpha", "beta"]
    assert data["default_id"] == "default" and all(item["available"] for item in data["items"])
    for forbidden in ("private", "api_key", "base_url", ".invalid", "Authorization"):
        assert forbidden not in result.text


def test_unconfigured_models_are_not_advertised_as_available(env, monkeypatch):
    monkeypatch.setattr(env.settings, "dashscope_api_key", "")
    monkeypatch.setattr(env.settings, "deepseek_api_key", "")
    catalog = model_catalog(env.settings)
    assert not catalog["items"][0]["available"]
    assert "dashscope" not in [item["id"] for item in catalog["items"]]
    assert "private-key" not in repr(env.settings.agent_models)


def test_model_preference_is_saved_without_reordering_and_checks_ownership_and_busy_state(env):
    identity = chat(env)
    with env.sessions() as db:
        before = db.get(ChatConversation, identity).updated_at
    path = f"/chat/conversations/{identity}/model"
    assert env.client.patch(path, headers=env.other, json={"model_id": "alpha"}).status_code == 404
    result = env.client.patch(path, headers=env.headers, json={"model_id": "alpha"})
    assert result.status_code == 200 and result.json()["model_id"] == "alpha"
    with env.sessions() as db:
        item = db.get(ChatConversation, identity)
        assert item.agent_model_id == "alpha" and item.updated_at == before
        item.generation_token = "busy"; item.generating_at = now_utc(); db.commit()
    assert env.client.patch(path, headers=env.headers, json={"model_id": "beta"}).status_code == 409


def test_omitted_model_uses_saved_conversation_preference_and_other_conversation_stays_default(env):
    identity, other = chat(env), chat(env)
    env.client.patch(f"/chat/conversations/{identity}/model", headers=env.headers, json={"model_id": "alpha"})
    with patch("app.modules.agent.completion.httpx.post", return_value=response({"relation": "new", "intent": {}})) as upstream, patch(
            "app.modules.chat.sending.run_agent", return_value={"answer": "已查询", "citations": []}):
        result = env.client.post(f"/chat/conversations/{identity}/ask", headers=env.headers,
            json={"content": "查询课程", "request_id": str(uuid4())})
        assert result.status_code == 200 and upstream.call_args.kwargs["json"]["model"] == "model-alpha"
    assert env.client.get(f"/chat/conversations/{other}/messages", headers=env.headers).json()["conversation"]["model_id"] == "default"


@pytest.mark.parametrize("stream", [False, True])
def test_unknown_model_and_client_credentials_cannot_create_messages_or_call_model(env, stream):
    identity = chat(env)
    endpoint = f"/chat/conversations/{identity}/ask" + ("/stream" if stream else "")
    body = {"content": "查询课程", "request_id": str(uuid4()), "model_id": "unknown"}
    with patch("app.modules.agent.completion.httpx.post") as upstream:
        rejected = env.client.post(endpoint, headers=env.headers, json=body)
        assert ("event: error" in rejected.text and "未配置或已下线" in rejected.text) if stream else rejected.status_code == 422
        injected = env.client.post(endpoint, headers=env.headers, json=body | {"api_key": "attacker", "base_url": "https://bad.invalid"})
        assert injected.status_code == 422
        upstream.assert_not_called()
    with env.sessions() as db:
        assert list(db.scalars(select(ChatMessage))) == []
        assert db.get(ChatConversation, identity).generation_token is None


@pytest.mark.parametrize("stream", [False, True])
def test_selected_model_drives_planning_tools_synthesis_and_checker_and_is_saved(env, stream):
    identity = chat(env, scoped=True)
    calls = [{"id": "read-1", "type": "function", "function": {"name": "get_transcript", "arguments": '{"lesson_id":"l"}'}}]
    replies = [response({"relation": "new", "intent": {"outputs": ["claims"]}}),
        response(None, calls=calls), response({"claims": [{"text": "二叉树最多两个孩子。", "source_ids": ["E1"]}]}),
        response({"paragraphs": [{"text": "二叉树的孩子数上限是两个。", "material_ids": ["claims"], "citation_ids": [1]}]}),
        response({"supported": True, "complete": True})]
    body = {"content": "解释二叉树的孩子数", "request_id": str(uuid4()), "model_id": "alpha"}
    endpoint = f"/chat/conversations/{identity}/ask" + ("/stream" if stream else "")
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        result = env.client.post(endpoint, headers=env.headers, json=body)
        assert result.status_code == 200, result.text
        if stream:
            assert "event: done" in result.text and "event: error" not in result.text, result.text
        assert upstream.call_count == 5
        for call in upstream.call_args_list:
            assert call.args[0] == "https://alpha.invalid/v1/chat/completions"
            assert call.kwargs["json"]["model"] == "model-alpha"
            assert call.kwargs["headers"]["Authorization"] == "Bearer private-key-alpha"
            assert "thinking" not in call.kwargs["json"] and "enable_thinking" not in call.kwargs["json"]
    saved = env.client.get(f"/chat/conversations/{identity}/messages", headers=env.headers).json()
    assert saved["conversation"]["model_id"] == "alpha"
    assert [item["model"]["id"] for item in saved["messages"]] == ["alpha", "alpha"]
    assert saved["messages"][-1]["content"] == "二叉树的孩子数上限是两个。 [1]"
    assert saved["messages"][-1]["citations"][0]["start_ms"] == 1000
    assert "private-key" not in json.dumps(saved) and "alpha.invalid" not in json.dumps(saved)
    assert active_chat_model() is None


def test_completed_request_replays_after_model_removal_but_cannot_change_model(env, monkeypatch):
    identity = chat(env)
    plan = {"relation": "new", "intent": {}}
    with env.sessions() as db, patch("app.modules.agent.completion.httpx.post", return_value=response(plan)), patch(
            "app.modules.chat.sending.run_agent", return_value={"answer": "已查询", "citations": []}):
        first = send_message(db, identity, "owner", "查询课程", "replay", model_id="alpha")
    monkeypatch.setattr(env.settings, "agent_models", [])
    with env.sessions() as db, patch("app.modules.agent.completion.httpx.post") as upstream:
        assert send_message(db, identity, "owner", "查询课程", "replay", model_id="alpha")["messages"] == first["messages"]
        with pytest.raises(HTTPException) as changed:
            send_message(db, identity, "owner", "查询课程", "replay", model_id="default")
        assert changed.value.status_code == 409
        upstream.assert_not_called()


def test_failed_retry_keeps_original_model_and_detects_reconfigured_id(env, monkeypatch):
    identity = chat(env)
    with env.sessions() as db, patch("app.modules.agent.completion.httpx.post", side_effect=httpx.ReadTimeout("private-key")):
        with pytest.raises(HTTPException):
            send_message(db, identity, "owner", "查询课程", "retry", model_id="alpha")
    with env.sessions() as db, patch("app.modules.agent.completion.httpx.post") as upstream:
        with pytest.raises(HTTPException) as changed:
            send_message(db, identity, "owner", "查询课程", "retry", model_id="beta")
        assert changed.value.status_code == 409
        monkeypatch.setattr(env.settings, "agent_models", [env.settings.agent_models[0].model_copy(update={"model": "changed-model"})])
        with pytest.raises(HTTPException) as changed:
            send_message(db, identity, "owner", "查询课程", "retry", model_id="alpha")
        assert changed.value.status_code == 409
        upstream.assert_not_called()
        saved = read_messages(db, identity, "owner")
        assert saved["messages"][0]["model"]["model"] == "model-alpha"
        assert saved["messages"][0]["status"] == "failed"
    assert active_chat_model() is None


def test_model_injection_is_isolated_between_concurrent_requests_and_resets_after_failure(env):
    barrier = Barrier(2)
    def generate(identity):
        with chat_model_scope():
            bind_chat_model(select_chat_model(env.settings, identity).target)
            barrier.wait(timeout=5)
            assert complete([], [], 2)["content"] == '"ok"'
            assert active_chat_model().model == f"model-{identity}"
        assert active_chat_model() is None
    with patch("app.modules.agent.completion.httpx.post", return_value=response("ok")) as upstream:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(generate, ["alpha", "beta"]))
    assert {call.kwargs["json"]["model"] for call in upstream.call_args_list} == {"model-alpha", "model-beta"}
    with pytest.raises(RuntimeError), chat_model_scope():
        bind_chat_model(select_chat_model(env.settings, "alpha").target)
        raise RuntimeError("cancelled")
    assert active_chat_model() is None


def test_cancelled_preview_keeps_model_metadata(env):
    identity = chat(env)
    metadata = select_chat_model(env.settings, "alpha").public()
    with env.sessions() as db:
        item = db.get(ChatConversation, identity)
        item.generation_token = "busy"; item.generating_at = now_utc()
        item.generation_preview_json = '{"answer":"部分回答","citations":[]}'
        db.add(ChatMessage(conversation_id=identity, request_id="cancel", position=1, role="user",
            content="查询课程", status="pending", agent_model_json=json.dumps(metadata))); db.commit()
        stopped = stop_generation(db, identity, "owner", "cancel")
        assert all(item["model"]["id"] == "alpha" and item["status"] == "cancelled" for item in stopped["messages"])


def test_model_selection_migration_is_repeatable_and_does_not_invent_old_message_model():
    engine = create_engine("sqlite:///:memory:")
    try:
        prepare_chat_model_selection(engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE chat_conversations (id TEXT PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE chat_messages (id TEXT PRIMARY KEY, content TEXT)"))
            connection.execute(text("INSERT INTO chat_conversations VALUES ('old')"))
            connection.execute(text("INSERT INTO chat_messages VALUES ('message', '旧回答')"))
        prepare_chat_model_selection(engine); prepare_chat_model_selection(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT agent_model_id FROM chat_conversations")).scalar() == "default"
            assert connection.execute(text("SELECT content, agent_model_json FROM chat_messages")).one() == ("旧回答", None)
    finally:
        engine.dispose()


@pytest.mark.parametrize("ids", [["repeat", "repeat"], ["default"], ["deepseek"], ["dashscope"]])
def test_catalog_rejects_duplicate_or_reserved_ids(ids):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, agent_models=[{"id": identity, "label": "模型", "provider": "deepseek", "model": "model"} for identity in ids])

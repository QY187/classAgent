"""多供应商协议及 Agent 工具循环；网络边界模拟，不调用付费 API。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.chat_failures import ChatRequestFailure
from app.core.config import Settings
from app.core.db import Base
from app.modules.agent.completion import complete
from app.modules.agent.loop import run_agent
from app.modules.agent.providers import resolve_chat_model
from app.modules.agent.tools import ToolContext
from app.shared.models import Course, Lesson, TranscriptSegment, User


def config():
    return SimpleNamespace(deepseek_api_key="legacy-secret", summary_model="legacy-model",
        dashscope_api_key="dashscope-secret", agent_provider="deepseek",
        agent_api_key="", agent_base_url="", agent_model="")


def configured(provider, **overrides):
    values = vars(config()) | {"agent_provider": provider} | overrides
    return SimpleNamespace(**values)


def reply(message=None, *, reason="stop", usage=None, status=200):
    return httpx.Response(status, json={"choices": [{"finish_reason": reason,
        "message": message or {"role": "assistant", "content": "模型回答"}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        request=httpx.Request("POST", "https://model.invalid/chat/completions"))


@pytest.mark.parametrize("provider,overrides,url,key,model,extra", [
    ("deepseek", {}, "https://api.deepseek.com/chat/completions", "legacy-secret", "legacy-model",
        {"thinking": {"type": "disabled"}}),
    ("dashscope", {}, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "dashscope-secret", "qwen-plus", {"enable_thinking": False}),
    ("openai_compatible", {"agent_base_url": "https://model.invalid/v1/", "agent_api_key": "custom-secret",
        "agent_model": "custom-model"}, "https://model.invalid/v1/chat/completions",
        "custom-secret", "custom-model", {}),
])
def test_provider_tool_protocol_and_trace(provider, overrides, url, key, model, extra):
    settings = configured(provider, **overrides)
    messages = [{"role": "user", "content": "查看我的课程"}]
    tools = [{"type": "function", "function": {"name": "list_courses", "parameters": {"type": "object"}}}]
    calls = [{"id": "call-1", "type": "function", "function": {"name": "list_courses", "arguments": "{}"}}]
    response = reply({"role": "assistant", "content": None, "tool_calls": calls,
                      "reasoning_content": "供应商内部思考"}, reason="tool_calls")
    with patch("app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.httpx.post", return_value=response) as post, patch(
            "app.modules.agent.completion.annotate") as annotate, patch(
            "app.modules.agent.completion.record_usage") as record:
        assert complete(messages, tools, 8) == {"role": "assistant", "content": None, "tool_calls": calls}
    assert post.call_args.args == (url,)
    assert post.call_args.kwargs == {"headers": {"Authorization": f"Bearer {key}"}, "timeout": 8,
        "json": {"model": model, "messages": messages, "temperature": 0, "max_tokens": 2500,
                 "tools": tools, "tool_choice": "auto", **extra}}
    annotate.assert_called_once_with(provider=provider, model=model, timeout_seconds=8)
    record.assert_called_once_with({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})


@pytest.mark.parametrize("provider", ["deepseek", "dashscope", "openai_compatible"])
def test_agent_overrides_are_independent_and_text_calls_do_not_send_tools(provider):
    settings = configured(provider, agent_base_url="https://custom.invalid/v1/chat/completions/",
        agent_api_key="agent-secret", agent_model="agent-model")
    with patch("app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.httpx.post", return_value=reply()) as post:
        assert complete([], [], 3)["content"] == "模型回答"
    assert post.call_args.args[0] == "https://custom.invalid/v1/chat/completions"
    body = post.call_args.kwargs["json"]
    assert body["model"] == "agent-model" and "tools" not in body and "tool_choice" not in body
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer agent-secret"
    assert settings.summary_model == "legacy-model" and settings.deepseek_api_key == "legacy-secret"
    assert "agent-secret" not in repr(resolve_chat_model(settings))


@pytest.mark.parametrize("overrides", [
    {"agent_provider": "unknown"},
    {"deepseek_api_key": ""},
    {"summary_model": " "},
    {"agent_provider": "dashscope", "dashscope_api_key": ""},
    {"agent_provider": "openai_compatible"},
    {"agent_provider": "openai_compatible", "agent_base_url": "https://model.invalid/v1", "agent_model": "model"},
    {"agent_provider": "openai_compatible", "agent_api_key": "secret", "agent_model": "model"},
    {"agent_provider": "openai_compatible", "agent_api_key": "secret", "agent_base_url": "https://model.invalid"},
    {"agent_base_url": "ftp://model.invalid"},
    {"agent_base_url": "https://user:secret@model.invalid"},
    {"agent_base_url": "https://model.invalid?api_key=secret"},
    {"agent_base_url": "https://model.invalid?"},
    {"agent_base_url": "https://model.invalid/#secret"},
    {"agent_base_url": "https://model.invalid/#"},
    {"agent_base_url": "https://"},
    {"agent_base_url": "not-a-url"},
])
def test_incomplete_or_unsafe_config_never_calls_network_or_reserves_quota(overrides):
    settings = configured("deepseek", **overrides)
    with patch("app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.quota_chat_post") as post, pytest.raises(ChatRequestFailure) as failure:
        complete([], [], 2)
    assert failure.value.failure.code == "ai_not_configured"
    assert "secret" not in failure.value.detail
    post.assert_not_called()


def test_settings_load_agent_environment_independently(monkeypatch):
    for name, value in {"AGENT_PROVIDER": "openai_compatible", "AGENT_BASE_URL": "https://model.invalid/v1",
                        "AGENT_API_KEY": "env-secret", "AGENT_MODEL": "env-model"}.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None, deepseek_api_key="legacy", summary_model="summary-only")
    model = resolve_chat_model(settings)
    assert (model.provider, model.model, model.api_key) == ("openai_compatible", "env-model", "env-secret")
    assert settings.summary_model == "summary-only"
    assert "env-secret" not in repr(settings)
    monkeypatch.setenv("AGENT_PROVIDER", "unsupported")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("failure,code", [
    (httpx.ReadTimeout("private-secret"), "model_timeout"),
    (httpx.ConnectError("private-secret"), "model_connection"),
    (401, "model_authentication"), (403, "model_permission"),
    (429, "model_rate_limited"), (500, "model_unavailable"),
])
def test_custom_provider_failures_are_public_and_never_fall_back(failure, code):
    settings = configured("openai_compatible", agent_base_url="https://model.invalid/v1",
        agent_api_key="private-secret", agent_model="model")
    kwargs = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": reply(status=failure)}
    with patch("app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.httpx.post", **kwargs) as post, pytest.raises(ChatRequestFailure) as caught:
        complete([], [], 2)
    assert caught.value.failure.code == code
    assert "private-secret" not in caught.value.detail
    assert post.call_count == 1


@pytest.mark.parametrize("payload", [None, {}, {"choices": []}, {"choices": [{"finish_reason": "length",
    "message": {"role": "assistant", "content": "截断"}}]}, {"choices": [{"finish_reason": "stop",
    "message": {"role": "assistant", "content": ["非文本"]}}]}])
def test_custom_provider_invalid_responses_are_rejected(payload):
    settings = configured("openai_compatible", agent_base_url="https://model.invalid",
        agent_api_key="secret", agent_model="model")
    response = httpx.Response(200, content=json.dumps(payload), request=httpx.Request("POST", "https://model.invalid"))
    with patch("app.modules.agent.completion.get_settings", return_value=settings), patch(
            "app.modules.agent.completion.httpx.post", return_value=response), pytest.raises(ChatRequestFailure) as failure:
        complete([], [], 2)
    assert failure.value.failure.code == "invalid_model_response"


@pytest.mark.parametrize("provider", ["deepseek", "dashscope", "openai_compatible"])
def test_full_tool_loop_reads_real_evidence_and_returns_citation(provider):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = configured(provider, agent_base_url="https://model.invalid/v1", agent_api_key="agent-secret",
        agent_model="agent-model")
    calls = [{"id": "read-1", "type": "function", "function": {"name": "get_transcript",
        "arguments": json.dumps({"lesson_id": "l"})}}]
    answers = [reply({"role": "assistant", "content": None, "tool_calls": calls}, reason="tool_calls"),
        reply({"role": "assistant", "content": json.dumps({"claims": [
            {"text": "二叉树最多两个孩子。", "source_ids": ["E1"]}]})})]
    try:
        with Session(engine) as db:
            db.add(User(id="u", username="owner", password_hash="x")); db.flush()
            db.add(Course(id="c", owner_id="u", name="数据结构")); db.flush()
            db.add(Lesson(id="l", course_id="c", title="二叉树")); db.flush()
            db.add(TranscriptSegment(id="s", lesson_id="l", speaker="老师", start_ms=1000,
                end_ms=2000, text="二叉树最多两个孩子。")); db.commit()
            with patch("app.modules.agent.completion.get_settings", return_value=settings), patch(
                    "app.modules.agent.completion.httpx.post", side_effect=answers) as post:
                result = run_agent(db, ToolContext("owner", "c"), "这节课如何定义二叉树？")
            assert result["outcome"] == "answered"
            assert result["citations"][0]["segment_ids"] == ["s"]
            assert result["citations"][0]["start_ms"] == 1000
            assert post.call_count == 2
            returned = [item for item in post.call_args.kwargs["json"]["messages"] if item["role"] == "tool"]
            assert returned[0]["tool_call_id"] == "read-1"
            assert json.loads(returned[0]["content"])["data"]["items"][0]["evidence_id"] == "E1"
    finally:
        engine.dispose()

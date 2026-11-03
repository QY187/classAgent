"""模型协议适配，不向外返回密钥、供应商异常或思考内容。"""
import httpx
from ...core.config import get_settings
from ...core.chat_failures import ChatRequestFailure, public_failure
from ...core.model_budget import quota_chat_post
from ...core.telemetry import annotate, record_usage, traced


@traced("model.chat", kind="model")
def complete(messages: list[dict], tools: list[dict], timeout: float) -> dict:
    settings = get_settings()
    annotate(provider="deepseek", model=settings.summary_model, timeout_seconds=timeout)
    if not settings.deepseek_api_key:
        raise ChatRequestFailure("ai_not_configured")
    try:
        response = quota_chat_post(httpx.post,
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={"model": settings.summary_model, "messages": messages,
                  **({"tools": tools, "tool_choice": "auto"} if tools else {}),
                  "temperature": 0, "max_tokens": 2500,
                  "thinking": {"type": "disabled"}},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        record_usage(payload.get("usage"))
        choice = payload["choices"][0]
        message = choice["message"]
        if choice.get("finish_reason") not in {"stop", "tool_calls"} or message.get("role") != "assistant":
            raise ValueError("Incomplete response")
        if not isinstance(message.get("content"), (str, type(None))):
            raise ValueError("Invalid content")
        return {"role": "assistant", "content": message.get("content"),
                **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {})}
    except httpx.TimeoutException as exc:
        raise ChatRequestFailure("model_timeout") from exc
    except httpx.HTTPError as exc:
        raise ChatRequestFailure(public_failure(exc)) from exc
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ChatRequestFailure("invalid_model_response") from exc

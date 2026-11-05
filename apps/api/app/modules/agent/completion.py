"""模型协议适配，不向外返回密钥、供应商异常或思考内容。"""
import httpx
from ...core.config import get_settings
from ...core.chat_failures import ChatRequestFailure, public_failure
from ...core.model_budget import quota_chat_post
from ...core.telemetry import annotate, record_usage, traced
from .providers import resolve_chat_model
from .model_selection import active_chat_model


@traced("model.chat", kind="model")
def complete(messages: list[dict], tools: list[dict], timeout: float) -> dict:
    settings = get_settings()
    model = active_chat_model() or resolve_chat_model(settings)
    annotate(provider=model.provider, model=model.model, timeout_seconds=timeout)
    if not model.api_key:
        raise ChatRequestFailure("ai_not_configured")
    try:
        response = quota_chat_post(httpx.post,
            model.url,
            headers={"Authorization": f"Bearer {model.api_key}"},
            json=model.request_body(messages, tools),
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

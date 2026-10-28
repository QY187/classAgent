"""模型协议适配，不向外返回密钥、供应商异常或思考内容。"""
import httpx
from fastapi import HTTPException
from ...core.config import get_settings


def complete(messages: list[dict], tools: list[dict], timeout: float) -> dict:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(503, "未配置 AI 服务，暂时无法执行 Agent")
    try:
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={"model": settings.summary_model, "messages": messages,
                  **({"tools": tools, "tool_choice": "auto"} if tools else {}),
                  "temperature": 0, "max_tokens": 2500,
                  "thinking": {"type": "disabled"}},
            timeout=timeout,
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        message = choice["message"]
        if choice.get("finish_reason") not in {"stop", "tool_calls"} or message.get("role") != "assistant":
            raise ValueError("Incomplete response")
        if not isinstance(message.get("content"), (str, type(None))):
            raise ValueError("Invalid content")
        return {"role": "assistant", "content": message.get("content"),
                **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {})}
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Agent 模型请求超时，请稍后重试") from exc
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "Agent 模型暂时无法返回有效结果") from exc

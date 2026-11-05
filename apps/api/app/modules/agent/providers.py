"""Agent 的服务端模型配置；不接受模型或客户端传入的供应商与密钥。"""
from dataclasses import dataclass, field

import httpx

from ...core.chat_failures import ChatRequestFailure


@dataclass(frozen=True)
class ChatModel:
    provider: str
    model: str
    url: str = field(repr=False)
    api_key: str = field(repr=False)

    def request_body(self, messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": self.model, "messages": messages,
                "temperature": 0, "max_tokens": 2500}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        # 思考开关是供应商扩展字段，不能透传给其他兼容接口。
        if self.provider == "deepseek":
            body["thinking"] = {"type": "disabled"}
        elif self.provider == "dashscope":
            body["enable_thinking"] = False
        return body


def resolve_chat_model(settings, *, require_key: bool = True) -> ChatModel:
    provider = getattr(settings, "agent_provider", "deepseek")
    base_url = getattr(settings, "agent_base_url", "").strip()
    api_key = getattr(settings, "agent_api_key", "").strip()
    model = getattr(settings, "agent_model", "").strip()
    if provider == "deepseek":
        base_url = base_url or "https://api.deepseek.com"
        api_key = api_key or settings.deepseek_api_key.strip()
        model = model or settings.summary_model.strip()
    elif provider == "dashscope":
        base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        api_key = api_key or settings.dashscope_api_key.strip()
        model = model or "qwen-plus"
    elif provider != "openai_compatible":
        raise ChatRequestFailure("ai_not_configured")
    if not base_url or not model or (require_key and not api_key):
        raise ChatRequestFailure("ai_not_configured")
    # 防止错误配置把密钥放进 URL；只在 Authorization 请求头传递密钥。
    try:
        parsed = httpx.URL(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.host
                or parsed.userinfo or "?" in base_url or "#" in base_url):
            raise ValueError("Invalid model endpoint")
    except (ValueError, httpx.InvalidURL) as exc:
        raise ChatRequestFailure("ai_not_configured") from exc
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return ChatModel(provider=provider, model=model, url=url, api_key=api_key)

"""服务端模型目录与请求级注入；公开接口不返回地址或凭证。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi import HTTPException

from ...core.chat_failures import ChatRequestFailure
from .providers import ChatModel, resolve_chat_model

_active_model = ContextVar("agent_selected_model", default=None)


@contextmanager
def chat_model_scope():
    token = _active_model.set(None)
    try:
        yield
    finally:
        _active_model.reset(token)


def bind_chat_model(model: ChatModel):
    _active_model.set(model)


def active_chat_model() -> ChatModel | None:
    return _active_model.get()


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    target: ChatModel

    def public(self):
        return {"id": self.id, "label": self.label, "provider": self.target.provider,
                "model": self.target.model, "available": bool(self.target.api_key)}


def model_options(settings) -> list[ModelOption]:
    options = []
    try:
        default = resolve_chat_model(settings, require_key=False)
        options.append(ModelOption("default", f"默认 · {default.model}", default))
    except ChatRequestFailure:
        pass
    presets = [
        {"id": "deepseek", "label": "DeepSeek", "provider": "deepseek",
         "model": getattr(settings, "summary_model", "deepseek-chat")},
        {"id": "dashscope", "label": "通义千问", "provider": "dashscope", "model": "qwen-plus"},
    ]
    configured = getattr(settings, "agent_models", [])
    for item in presets + [item.model_dump() for item in configured]:
        target_settings = SimpleNamespace(agent_provider=item["provider"], agent_model=item["model"],
            agent_base_url=item.get("base_url", ""), agent_api_key=item.get("api_key", ""),
            deepseek_api_key=getattr(settings, "deepseek_api_key", ""),
            summary_model=getattr(settings, "summary_model", "deepseek-chat"),
            dashscope_api_key=getattr(settings, "dashscope_api_key", ""))
        try:
            target = resolve_chat_model(target_settings)
        except ChatRequestFailure:
            continue
        # 预设与默认完全相同时只显示一次；自定义编号保留，便于稳定引用。
        if item["id"] in {"deepseek", "dashscope"} and any(target == option.target for option in options):
            continue
        label = item["label"] if item["id"] not in {"deepseek", "dashscope"} else f'{item["label"]} · {target.model}'
        options.append(ModelOption(item["id"], label, target))
    return options


def select_chat_model(settings, model_id: str) -> ModelOption:
    option = next((item for item in model_options(settings) if item.id == model_id), None)
    if option is None:
        raise HTTPException(422, "所选模型未配置或已下线，请重新选择模型")
    return option


def model_catalog(settings) -> dict:
    return {"default_id": "default", "items": [option.public() for option in model_options(settings)]}

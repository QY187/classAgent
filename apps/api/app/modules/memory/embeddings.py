"""记忆向量调用独立限时和额度记账；不可用时由调用方降级。"""
import math
import httpx
from ...core.config import get_settings
from ...core.model_budget import model_reservation
from ...core.telemetry import record_usage, traced, annotate


def embed(text, *, timeout=4):
    settings = get_settings()
    if not settings.dashscope_api_key or settings.embedding_dim != 1536:
        return None
    return _embed(text,timeout,settings)


@traced("memory.embedding",kind="model")
def _embed(text,timeout,settings):
    annotate(provider="dashscope",model=settings.embedding_model,timeout_seconds=timeout)
    body = {"model": settings.embedding_model, "input": [text], "max_tokens": 1}
    with model_reservation({**body, "messages": [{"role":"user","content":text}]}, purpose="memory_embedding") as reservation:
        if reservation:
            reservation.sent = True
        response = httpx.post(settings.embedding_base_url.rstrip("/") + "/embeddings",
            headers={"Authorization": "Bearer " + settings.dashscope_api_key},
            json={k:v for k,v in body.items() if k != "max_tokens"}, timeout=timeout)
        if reservation and response.status_code in {400,401,403,404,422,429}:
            reservation.settle(0)
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage")
        if reservation:
            reservation.usage(usage)
        record_usage(usage)
        vector = payload["data"][0]["embedding"]
        if not isinstance(vector,list) or len(vector)!=1536 or not all(type(x) in (int,float) and math.isfinite(x) for x in vector):
            raise ValueError("Invalid memory embedding")
        return vector

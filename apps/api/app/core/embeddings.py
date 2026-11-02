import httpx

from .config import get_settings
from .telemetry import annotate, record_usage, traced


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法建立课程问答索引")
    result: list[list[float]] = []
    with httpx.Client(timeout=60) as client:
        for offset in range(0, len(texts), 25):
            batch = texts[offset:offset + 25]
            result.extend(_embed_batch(client, batch, settings))
    return result


@traced("model.embedding", kind="model")
def _embed_batch(client, batch, settings):
    annotate(provider="dashscope", model=settings.embedding_model, batch_size=len(batch), timeout_seconds=60)
    try:
        response = client.post(
            f"{settings.embedding_base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            json={"model": settings.embedding_model, "input": batch},
        )
    except httpx.HTTPError as exc:
        raise RuntimeError("向量服务暂时不可用，请稍后重试") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"向量服务请求失败（{response.status_code}）")
    try:
        payload = response.json()
        record_usage(payload.get("usage"))
        items = sorted(payload.get("data", []), key=lambda item: item["index"])
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("向量服务返回格式错误") from exc
    if len(items) != len(batch):
        raise RuntimeError("向量服务返回数量不匹配")
    result = []
    for item in items:
        vector = item.get("embedding", [])
        if len(vector) != settings.embedding_dim:
            raise RuntimeError("向量维度与配置不匹配，请检查模型设置")
        result.append(vector)
    return result

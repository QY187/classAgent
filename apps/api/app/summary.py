import json
import re
from typing import Any

import httpx

from .config import get_settings


SUMMARY_SCHEMA = {
    "overview": "一句话概览",
    "topics": [{"title": "主题标题", "time_range": "00:00-00:00", "points": ["要点"], "source_indexes": [1]}],
    "key_concepts": [{"term": "概念", "definition": "课堂语境中的定义", "source_indexes": [1]}],
    "examples": [{"title": "例题或案例", "explanation": "讲解思路和结论", "source_indexes": [1]}],
    "assignments": ["录音中明确提到的作业或下节课安排"],
    "to_verify": ["听不清、上下文不足或需要回听确认的内容"],
}


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("模型返回的纪要不是 JSON 对象")
    return value


def generate_summary(segments: list[dict[str, Any]]) -> str:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法生成智能纪要")
    if not segments:
        raise RuntimeError("当前课次还没有文字记录，无法生成智能纪要")

    transcript = "\n".join(
        f"[{item['index']}] [{item['start']}–{item['end']}] {item['speaker']}：{item['text']}"
        for item in segments
    )
    system_prompt = (
        "你是课堂学习助手。请只根据提供的课堂文字记录生成纪要，不补充录音之外的常识，不猜测作业、日期、公式或人名。"
        "所有不确定的内容放入 to_verify。输出严格 JSON，不要输出 Markdown 或额外解释。"
    )
    user_prompt = (
        "请按这个结构生成课堂纪要：\n"
        f"{json.dumps(SUMMARY_SCHEMA, ensure_ascii=False)}\n\n"
        "要求：overview 简洁；topics 按课堂推进顺序；每个重点引用 source_indexes；没有提到的例题、作业或预告输出空数组。\n\n"
        f"课堂文字记录：\n{transcript}"
    )
    response = httpx.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"},
        json={
            "model": settings.summary_model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.2,
        },
        timeout=120,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"DeepSeek 纪要请求失败（{response.status_code}）：{detail}")
    data = response.json()
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not text:
        raise RuntimeError("DeepSeek 没有返回纪要内容")
    return json.dumps(_parse_json(text), ensure_ascii=False)

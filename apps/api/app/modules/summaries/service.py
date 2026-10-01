import json
import re
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...shared.models import Lesson, LessonSummary
from . import mapper


SUMMARY_SCHEMA = {
    "overview": "用 2-3 句话说明本节课讲了什么、怎样推进以及最终结论",
    "learning_goals": ["从课堂记录中归纳出的学习目标；没有明确依据时输出空数组"],
    "chapter_flow": [{"title": "章节或主题标题", "time_range": "00:00-00:00", "summary": "这一部分讲了什么", "source_indexes": [1]}],
    "topics": [{"title": "主题标题", "time_range": "00:00-00:00", "summary": "主题概述", "points": ["要点"], "takeaway": "这一主题最后应记住什么", "source_indexes": [1]}],
    "key_concepts": [{"term": "概念", "definition": "课堂语境中的定义", "importance": "为什么重要或如何使用", "source_indexes": [1]}],
    "key_takeaways": ["可以直接用于复习的关键结论或方法"],
    "examples": [{"title": "例题或案例", "context": "题目或案例背景", "explanation": "讲解思路和步骤", "conclusion": "最终结论", "source_indexes": [1]}],
    "teacher_emphasis": ["老师明确强调、提醒或反复说明的内容"],
    "assignments": ["录音中明确提到的作业或下节课安排"],
    "questions": ["课堂中提出但没有完整解决的问题"],
    "to_verify": ["听不清、上下文不足或需要回听确认的内容"],
    "keywords": ["本节课的关键词"],
    "review_questions": ["根据课堂内容生成的复习自测问题；答案必须能在记录中找到"],
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
        "文字记录和智能纪要是两个独立产物：纪要负责提炼结构和复习线索，不能把整段逐字稿重新复制一遍。"
        "所有不确定的内容放入 to_verify；没有依据的数组必须为空。输出严格 JSON，不要输出 Markdown 或额外解释。"
    )
    user_prompt = (
        "请按这个结构生成课堂纪要：\n"
        f"{json.dumps(SUMMARY_SCHEMA, ensure_ascii=False)}\n\n"
        "要求：overview 用 2-3 句话；chapter_flow 和 topics 按课堂推进顺序；每个实质性结论、概念、例题和复习问题都要引用 source_indexes；"
        "topics 每项给出 summary、2-4 条 points 和 takeaway；例题尽量拆成背景、思路、结论；"
        "teacher_emphasis 只保留老师明确强调的内容；没有提到的例题、作业、问题或预告输出空数组；"
        "纪要要有足够信息帮助复习，但不要为了充实而编造内容。\n\n"
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


def _owned_lesson(db: Session, lesson_id: str, owner_username: str) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or lesson.course.owner_username != owner_username:
        raise HTTPException(status_code=404, detail="课次不存在")
    return lesson


def get_summary(db: Session, lesson_id: str, owner_username: str) -> LessonSummary:
    _owned_lesson(db, lesson_id, owner_username)
    summary = mapper.find_summary(db, lesson_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="该课次暂无智能纪要")
    return summary


def request_summary(db: Session, lesson_id: str, owner_username: str) -> LessonSummary:
    _owned_lesson(db, lesson_id, owner_username)
    if not mapper.has_transcript(db, lesson_id):
        raise HTTPException(status_code=400, detail="请先完成文字记录，再生成智能纪要")
    summary = mapper.find_summary(db, lesson_id)
    if summary is None:
        summary = LessonSummary(lesson_id=lesson_id, provider=get_settings().summary_provider)
        db.add(summary)
    summary.status = "queued"
    summary.error_message = None
    db.commit()
    db.refresh(summary)
    from ...infrastructure.tasks import generate_summary as generate_summary_task

    generate_summary_task.delay(lesson_id)
    return summary


def update_summary_content(db: Session, lesson_id: str, content: str, owner_username: str) -> LessonSummary:
    _owned_lesson(db, lesson_id, owner_username)
    summary = mapper.find_summary(db, lesson_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="该课次还没有智能纪要，请先生成")
    summary.content = content
    summary.status = "edited"
    summary.error_message = None
    db.commit()
    db.refresh(summary)
    from ...infrastructure.tasks import reindex_lesson
    reindex_lesson.delay(lesson_id)
    return summary

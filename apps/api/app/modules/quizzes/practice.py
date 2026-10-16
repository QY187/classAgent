"""从真实学习记录确定练习主题和课堂来源，独立于普通小测范围选择。"""
from dataclasses import dataclass

from fastapi import HTTPException

from ...core.visibility import visible_get
from ...shared.models import Lesson, QuizQuestion, ReviewCard, TranscriptSegment


@dataclass(frozen=True)
class PracticeSelection:
    knowledge_point_ids: tuple[str, ...] = ()
    wrong_question_ids: tuple[str, ...] = ()


@dataclass
class PracticeMaterial:
    segments: list
    topics: list[str]
    windows: dict[str, str]
    signature: list[tuple]


def practice_material(db, course_id, username, selection):
    from .service import _owned_course, list_wrong_questions
    _owned_course(db, course_id, username)
    if (not selection.knowledge_point_ids and not selection.wrong_question_ids
            or len(selection.knowledge_point_ids) > 20 or len(selection.wrong_question_ids) > 20):
        raise HTTPException(400, "请选择 1 到 40 个知识点或错题")
    db.expire_all()
    pending = {row["id"]: row for row in list_wrong_questions(db, username, course_id) if row["status"] == "pending"} if selection.wrong_question_ids else {}
    segments, topics, windows, signature = {}, [], {}, []

    def add(kind, record, lesson_id, topic, status):
        source = visible_get(db, TranscriptSegment, record.source_segment_id) if record.source_segment_id else None
        lesson = visible_get(db, Lesson, lesson_id) if lesson_id else None
        if (source is None or lesson is None or lesson.course_id != course_id
                or source.lesson_id != lesson.id or not source.text.strip()):
            raise HTTPException(400, "所选学习记录缺少当前可核对的课堂原文，请先补充来源或选择其他记录")
        excerpt = record.source_excerpt
        if excerpt and excerpt not in source.text:
            raise HTTPException(400, "学习记录对应的课堂原文已变化，请先核对来源再出题")
        segments[source.id] = source
        topics.append(topic)
        signature.append((kind, record.id, status, topic, source.id, source.text, excerpt))
        # 保留引用附近文字，避免相关内容位于长片段尾部时被普通截短丢掉。
        start = source.text.find(excerpt) if excerpt else 0
        target = max(0, start - 80)
        window = source.text[target:target + 600]
        prior = windows.get(source.id, "")
        if window not in prior:
            windows[source.id] = (prior + "\n" + window).strip()

    for identity in dict.fromkeys(selection.knowledge_point_ids):
        card = visible_get(db, ReviewCard, identity)
        if card is None or card.course_id != course_id or card.status != "review":
            raise HTTPException(400, "知识点不存在、不属于当前课程或不是需要复习状态，请重新查询")
        add("knowledge", card, card.lesson_id, f"知识点：{card.title}；内容：{card.body[:400]}", card.status)
    for identity in dict.fromkeys(selection.wrong_question_ids):
        question = visible_get(db, QuizQuestion, identity)
        if identity not in pending or question is None:
            raise HTTPException(400, "错题不存在、不属于当前课程或已经答对，请重新查询")
        add("wrong", question, question.source_lesson_id, f"错题主题：{question.stem}", "pending")
    return PracticeMaterial(list(segments.values()), topics, windows, signature)

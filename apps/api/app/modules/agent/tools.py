"""把现有业务封装为读取工具，不执行模型生成的代码。"""
import json
from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..courses import service as courses
from ..lessons import service as lessons
from ..summaries import service as summaries
from ..rag.service import owned_course, hybrid_retrieve
from ..search.mapper import search_all
from .schemas import CourseListArguments, LessonListArguments, TranscriptArguments, SummaryArguments, SearchArguments


@dataclass(frozen=True)
class ToolContext:
    # 只能由后端根据已认证用户和对话构造，不作为模型可填写的参数。
    username: str
    course_id: str | None = None
    lesson_id: str | None = None
    generate_quiz: Callable | None = field(default=None, compare=False, repr=False)
    practice_only: bool = False
    actions: dict[str, Callable] = field(default_factory=dict, compare=False, repr=False)
    action_hints: dict = field(default_factory=dict, compare=False, repr=False)


def generate_quiz(db, context, args):
    if context.generate_quiz is None or context.practice_only:
        raise HTTPException(403, "当前问题没有授权生成小测")
    check_course(db, context, args.course_id)
    for lesson_id in args.lesson_ids or []:
        lesson = check_lesson(db, context, lesson_id)
        if lesson.course_id != args.course_id:
            raise HTTPException(404, "课次不存在")
    return context.generate_quiz(args)


def generate_practice_quiz(db, context, args):
    if context.generate_quiz is None or not context.practice_only:
        raise HTTPException(403, "当前问题没有授权生成薄弱点练习")
    check_course(db, context, args.course_id)
    return context.generate_quiz(args)


def check_course(db: Session, context: ToolContext, course_id: str):
    if context.course_id is not None and course_id != context.course_id:
        raise HTTPException(404, "课程不存在")
    return owned_course(db, course_id, context.username)


def check_lesson(db: Session, context: ToolContext, lesson_id: str):
    if context.lesson_id is not None and lesson_id != context.lesson_id:
        raise HTTPException(404, "课次不存在")
    lesson = lessons.get_lesson(db, lesson_id, context.username)
    check_course(db, context, lesson.course_id)
    return lesson


def page(items: list, offset: int, limit: int) -> dict:
    selected = items[offset:offset + limit]
    end = offset + len(selected)
    return {"items": selected, "total": len(items), "next_offset": end if end < len(items) else None}


def list_courses(db: Session, context: ToolContext, args: CourseListArguments) -> dict:
    rows = courses.list_courses(db, context.username)
    return page([{"id": row.id, "name": row.name, "semester": row.semester}
                 for row in rows if (context.course_id is None or row.id == context.course_id)
                 and args.query.casefold() in row.name.casefold()], args.offset, args.limit)


def list_lessons(db: Session, context: ToolContext, args: LessonListArguments) -> dict:
    check_course(db, context, args.course_id)
    rows = courses.list_lessons(db, args.course_id, context.username)
    return page([{"id": row.id, "course_id": row.course_id, "title": row.title,
                  "lesson_date": row.lesson_date, "status": row.status}
                 for row in rows if (context.lesson_id is None or row.id == context.lesson_id)
                 and args.query.casefold() in row.title.casefold()], args.offset, args.limit)


def get_transcript(db: Session, context: ToolContext, args: TranscriptArguments) -> dict:
    lesson = check_lesson(db, context, args.lesson_id)
    rows = lessons.get_transcript(db, args.lesson_id, context.username)
    result = page([{"segment_id": row.id, "speaker": row.speaker, "start_ms": row.start_ms,
                    "end_ms": row.end_ms, "text": row.text[:2000], "truncated": len(row.text) > 2000}
                   for row in rows], args.offset, args.limit)
    return {"course_id": lesson.course_id, "lesson_id": lesson.id, **result}


def get_summary(db: Session, context: ToolContext, args: SummaryArguments) -> dict:
    lesson = check_lesson(db, context, args.lesson_id)
    summary = summaries.get_summary(db, args.lesson_id, context.username)
    # 排队、失败或过期纪要不能当作已经完成的课堂材料。
    available = summary.status in {"completed", "edited"} and bool(summary.content)
    content = summary.content if available else ""
    end = args.offset + args.limit
    return {"course_id": lesson.course_id, "lesson_id": lesson.id, "status": summary.status,
            "available": available, "content": content[args.offset:end], "total_characters": len(content),
            "next_offset": end if end < len(content) else None}


def search_course(db: Session, context: ToolContext, args: SearchArguments) -> dict:
    check_course(db, context, args.course_id)
    lesson_id = args.lesson_id or context.lesson_id
    if lesson_id is not None:
        lesson = check_lesson(db, context, lesson_id)
        if lesson.course_id != args.course_id:
            raise HTTPException(404, "课次不存在")
    rows = hybrid_retrieve(db, args.course_id, context.username, args.query, lesson_id=lesson_id, limit=args.limit)
    if not rows:
        # 尚未建立向量索引时保留可用的精确词法回退，重建索引后自动走混合召回。
        legacy = search_all(db, args.query, context.username, course_id=args.course_id,
                            kind="transcript", lesson_id=lesson_id)["transcript"]
        return {"course_id": args.course_id, "lesson_id": lesson_id, "query": args.query,
                "retrieval_method": "keyword", "has_more": len(legacy) > args.limit or len(legacy) == 30,
                "items": [{"segment_id": row["segment_id"], "lesson_id": row["lesson_id"],
                           "lesson_title": row["lesson_title"], "start_ms": row["start_ms"],
                           "snippet": row["snippet"]} for row in legacy[:args.limit]]}
    lessons_by_id = {row.id: lessons.get_lesson(db, row.lesson_id, context.username) for row in rows}
    return {"course_id": args.course_id, "lesson_id": lesson_id, "query": args.query,
            "retrieval_method": "hybrid_bm25_vector", "has_more": False,
            "items": [{"segment_id": source_ids[0] if source_ids else row.id, "lesson_id": row.lesson_id,
                       "lesson_title": lessons_by_id[row.lesson_id].title, "start_ms": row.start_ms,
                       "snippet": row.content[:500], "source_segment_ids": source_ids}
                      for row in rows[:args.limit]
                      for source_ids in [json.loads(row.source_segment_ids)] ]}

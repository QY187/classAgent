"""仅从实际读取的文字片段建立引用，再次核对权限与内容版本。"""
import json
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ...shared.models import TranscriptSegment
from ..rag.service import ground_claims
from .tools import ToolContext, check_lesson
from .learning import LearningStore
from .quiz_results import QuizResultStore
from .progress import ProgressStore
from .workflow_queries import WorkflowQueryStore


class EvidenceStore:
    def __init__(self):
        self.entries = {}
        self.course_ids = set()
        self.lesson_ids = set()
        self.learning = LearningStore()
        self.quiz_results = QuizResultStore()
        self.progress = ProgressStore()
        self.workflow = WorkflowQueryStore()

    def collect(self, db: Session, context: ToolContext, name: str, result: dict):
        if not result["ok"]:
            return
        self.learning.collect(name, result)
        self.quiz_results.collect(name, result)
        self.progress.collect(name, result)
        self.workflow.collect(name, result)
        if name in {"list_courses", "list_lessons"}:
            target = self.course_ids if name == "list_courses" else self.lesson_ids
            target.update(row["id"] for row in result["data"]["items"])
            return
        if name not in {"get_transcript", "search_course"}:
            return
        data = result["data"]
        for row in data.get("items", []):
            segment = db.scalar(select(TranscriptSegment).where(TranscriptSegment.id == row["segment_id"]))
            if segment is None:
                continue
            lesson = check_lesson(db, context, segment.lesson_id)
            content = row.get("text") or row.get("snippet")
            if not content:
                continue
            key = f"E{len(self.entries) + 1}"
            self.entries[key] = {"segment_id": segment.id, "snapshot": segment.text,
                                 "lesson_id": lesson.id, "content": content}
            row["evidence_id"] = key

    def answer(self, db: Session, context: ToolContext, claims: list, *, citation_offset: int = 0) -> dict:
        evidence, lessons = {}, {}
        for key, entry in self.entries.items():
            segment = db.scalar(select(TranscriptSegment).where(TranscriptSegment.id == entry["segment_id"])
                                .execution_options(populate_existing=True))
            if segment is None or segment.text != entry["snapshot"]:
                continue
            try:
                lesson = check_lesson(db, context, segment.lesson_id)
            except HTTPException:
                continue
            if segment.lesson_id != entry["lesson_id"]:
                continue
            evidence[key] = SimpleNamespace(lesson_id=lesson.id, start_ms=segment.start_ms,
                end_ms=segment.end_ms, content=entry["content"], source_segment_ids=json.dumps([segment.id]))
            lessons[lesson.id] = lesson
        return ground_claims(claims, evidence, lessons, citation_offset=citation_offset)

    def catalog_answer(self, db: Session, context: ToolContext, catalog: dict) -> list[str]:
        from .tools import check_course
        lines = []
        for key, allowed in (("course_ids", self.course_ids), ("lesson_ids", self.lesson_ids)):
            ids = catalog.get(key, [])
            if not isinstance(ids, list):
                continue
            for identity in dict.fromkeys(value for value in ids[:50] if isinstance(value, str)):
                if identity not in allowed:
                    continue
                try:
                    if key == "course_ids":
                        course = check_course(db, context, identity)
                        lines.append(f"课程：{course.name}" + (f" · {course.semester}" if course.semester else ""))
                    else:
                        lesson = check_lesson(db, context, identity)
                        course = check_course(db, context, lesson.course_id)
                        lines.append(f"课次：{lesson.title} · {course.name}" + (f" · {lesson.lesson_date}" if lesson.lesson_date else ""))
                except HTTPException:
                    continue
        return lines

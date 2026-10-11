"""仅从实际读取的文字片段建立引用，再次核对权限与内容版本。"""
import json
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ...shared.models import TranscriptSegment
from ..rag.service import ground_claims
from .tools import ToolContext, check_lesson


class EvidenceStore:
    def __init__(self):
        self.entries = {}

    def collect(self, db: Session, context: ToolContext, name: str, result: dict):
        if not result["ok"] or name not in {"get_transcript", "search_course"}:
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

    def answer(self, db: Session, context: ToolContext, claims: list) -> dict:
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
        return ground_claims(claims, evidence, lessons)

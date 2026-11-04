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
from .claim_validation import verified_claims
from .progress import ProgressStore
from .workflow_queries import WorkflowQueryStore


class EvidenceStore:
    def __init__(self):
        self.entries = {}
        self.catalog_reads = []
        self.course_ids = set()
        self.lesson_ids = set()
        self.learning = LearningStore()
        self.quiz_results = QuizResultStore()
        self.progress = ProgressStore()
        self.workflow = WorkflowQueryStore()

    def collect(self, db: Session, context: ToolContext, name: str, result: dict, arguments=None):
        if not result["ok"]:
            return
        self.learning.collect(name, result)
        self.quiz_results.collect(name, result)
        self.progress.collect(name, result)
        self.workflow.collect(name, result)
        if name in {"list_courses", "list_lessons"}:
            self.catalog_reads.append((name, arguments or {}, result["data"]))
            target = self.course_ids if name == "list_courses" else self.lesson_ids
            target.update(row["id"] for row in result["data"]["items"])
            return
        if name not in {"get_transcript", "search_course"}:
            return
        data = result["data"]
        for row in data.get("items", []):
            content = row.get("text") or row.get("snippet")
            if not content:
                continue
            # 父块只是检索上下文，不能把整个父块都绑定到第一个（常为标题）片段。
            source_ids = row.get("source_segment_ids") or [row["segment_id"]]
            sources = []
            for identity in dict.fromkeys(source_ids):
                segment = db.get(TranscriptSegment, identity)
                if segment is None or segment.lesson_id != row.get("lesson_id", data.get("lesson_id")):
                    continue
                try:
                    lesson = check_lesson(db, context, segment.lesson_id)
                except HTTPException:
                    continue
                if data.get("course_id") and lesson.course_id != data["course_id"]:
                    continue
                # 只认证模型本轮确实读到的文字，不从父块 ID 列表偷偷补入截断外的原文。
                excerpt = content.strip("…")
                visible = segment.text if segment.text in content else (
                    excerpt if len(source_ids) == 1 and excerpt and excerpt in segment.text else None)
                if not visible:
                    continue
                key = next((key for key, entry in self.entries.items()
                            if entry["segment_id"] == segment.id and entry["content"] == visible
                            and entry["snapshot"] == segment.text), None)
                if key is None:
                    key = f"E{len(self.entries) + 1}"
                    self.entries[key] = {"segment_id": segment.id, "snapshot": segment.text,
                                         "lesson_id": lesson.id, "content": visible}
                sources.append({"evidence_id": key, "text": visible,
                                "start_ms": segment.start_ms, "end_ms": segment.end_ms})
            row["evidence"] = sources
            if sources:
                row["evidence_id"] = sources[0]["evidence_id"]

    def answer(self, db: Session, context: ToolContext, claims: list, *, citation_offset: int = 0) -> dict:
        from .goals import requested_outputs
        evidence, lessons = self.current_evidence(db, context)
        compact = requested_outputs(context) is not None
        verified = verified_claims(claims, evidence, fallback=not compact)
        result = ground_claims(verified, evidence, lessons, citation_offset=citation_offset)
        if compact and len(verified) > 1:
            result["answer"] = "\n\n".join("- " + line for line in result["answer"].split("\n\n"))
        return result

    def current_evidence(self, db: Session, context: ToolContext):
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
                end_ms=segment.end_ms, content=entry["content"], full_content=segment.text, source_segment_ids=json.dumps([segment.id]))
            lessons[lesson.id] = lesson
        return evidence, lessons

    def location_answer(self, db: Session, context: ToolContext, selection: dict, *, citation_offset: int = 0, concise=False):
        from .tools import check_course
        ids = selection["source_ids"]
        if any(key not in self.entries for key in ids):
            raise ValueError("位置引用必须来自本次实际读取的原文")
        db.expire_all()
        evidence, lessons = self.current_evidence(db, context)
        claims, seen = [], set()
        for key in dict.fromkeys(ids):
            if key not in evidence:
                continue
            lesson = lessons[evidence[key].lesson_id]
            if lesson.id in seen:
                continue
            course = check_course(db, context, lesson.course_id)
            claims.append({"text": f"《{course.name}》 · {lesson.title}", "source_ids": [key]})
            seen.add(lesson.id)
        if not claims:
            return {"answer": "目前没有足够的有效原文依据定位到具体课程和课次。", "citations": []}
        # 只使用重新核验的数据库元数据，绕过课堂原文逐句匹配；不接受模型自由填写名称或序号。
        result = ground_claims(claims, evidence, lessons, citation_offset=citation_offset)
        if not concise:
            result["answer"] = "找到相关内容：\n\n" + result["answer"]
        return result

    def catalog_selection(self, kinds):
        selected = {"course_ids":[], "lesson_ids":[]}
        for name, args, data in self.catalog_reads:
            if name in kinds and not args.get("query"):
                key = "course_ids" if name == "list_courses" else "lesson_ids"
                selected[key].extend(row["id"] for row in data["items"])
        return selected

    def catalog_complete(self, kinds):
        for kind in kinds:
            reads = [(args, data) for name, args, data in self.catalog_reads if name == kind and not args.get("query")]
            scopes = {args.get("course_id") for args, _ in reads}
            complete = False
            for scope in scopes:
                pages = {args.get("offset",0):data for args,data in reads if args.get("course_id") == scope}
                offset, seen = 0, set()
                while offset in pages and offset not in seen:
                    seen.add(offset)
                    following = pages[offset].get("next_offset")
                    if following is None:
                        complete = True
                        break
                    offset = following
            if not complete:
                return False
        return True

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

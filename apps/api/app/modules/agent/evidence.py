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
        self.material_ids = set()
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
        if name in {"list_courses", "list_lessons", "list_materials"}:
            self.catalog_reads.append((name, arguments or {}, result["data"]))
            target = {"list_courses": self.course_ids, "list_lessons": self.lesson_ids, "list_materials": self.material_ids}[name]
            target.update(row["id"] for row in result["data"]["items"])
            return
        if name not in {"get_transcript", "search_course", "get_material_content"}:
            return
        data = result["data"]
        for row in data.get("items", []):
            if row.get("source_type") == "material":
                self.collect_material(db, context, row)
                continue
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
                            if entry.get("segment_id") == segment.id and entry["content"] == visible
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

    def collect_material(self, db, context, row):
        from .material_tools import check_material, source_preference
        from ..materials.content import current_material_chunk
        if source_preference(context) == "transcript":
            return
        chunk = current_material_chunk(db, row.get("chunk_id"))
        if chunk is None or chunk.material_id != row.get("material_id") or chunk.version != row.get("version"):
            return
        try:
            material = check_material(db, context, row.get("course_id"), chunk.material_id)
        except HTTPException:
            return
        visible = row.get("text") or row.get("snippet") or ""
        if not visible or visible not in chunk.content:
            return
        key = next((key for key, entry in self.entries.items() if entry.get("chunk_id") == chunk.id
                    and entry["content"] == visible and entry["snapshot"] == chunk.content), None)
        if key is None:
            key = f"E{len(self.entries) + 1}"
            self.entries[key] = {"chunk_id": chunk.id, "snapshot": chunk.content, "content": visible,
                                 "material_id": material.id, "version": chunk.version, "course_id": material.course_id,
                                 "lesson_id": material.lesson_id, "source_type": "material"}
        row["evidence_id"] = key
        row["evidence"] = [{"evidence_id": key, "text": visible, "source_type": "material",
                            "filename": material.filename, "locator_type": chunk.locator_type,
                            "locator_number": chunk.locator_number}]

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
            if entry.get("source_type") == "material":
                from .material_tools import check_material
                from ..materials.content import current_material_chunk
                chunk = current_material_chunk(db, entry["chunk_id"])
                if chunk is None or chunk.version != entry["version"] or chunk.content != entry["snapshot"]:
                    continue
                try:
                    material = check_material(db, context, entry["course_id"], entry["material_id"])
                except HTTPException:
                    continue
                if material.lesson_id != entry["lesson_id"]:
                    continue
                evidence[key] = SimpleNamespace(source_type="material", course_id=material.course_id,
                    material_id=material.id, filename=material.filename, lesson_id=material.lesson_id,
                    chunk_id=chunk.id, version=chunk.version, position=chunk.position,
                    locator_type=chunk.locator_type, locator_number=chunk.locator_number,
                    start_ms=None, end_ms=None, content=entry["content"], full_content=chunk.content,
                    source_segment_ids="[]")
                if material.lesson_id:
                    lessons[material.lesson_id] = check_lesson(db, context, material.lesson_id)
                continue
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
            from .material_tools import source_preference
            if source_preference(context) == "material":
                continue
            evidence[key] = SimpleNamespace(course_id=lesson.course_id, lesson_id=lesson.id, start_ms=segment.start_ms,
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
            item = evidence[key]
            if getattr(item, "source_type", None) == "material":
                from ..materials.content import locator_label
                identity = (item.material_id, item.locator_type, item.locator_number)
                if identity not in seen:
                    course = check_course(db, context, item.course_id)
                    claims.append({"text": f"《{course.name}》 · {item.filename} · {locator_label(item.locator_type, item.locator_number)}",
                                   "source_ids": [key]})
                    seen.add(identity)
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
        if "list_materials" in kinds:
            selected["material_ids"] = []
        for name, args, data in self.catalog_reads:
            if name in kinds and not args.get("query"):
                key = {"list_courses": "course_ids", "list_lessons": "lesson_ids", "list_materials": "material_ids"}[name]
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
        for key, allowed in (("course_ids", self.course_ids), ("lesson_ids", self.lesson_ids), ("material_ids", self.material_ids)):
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
                    elif key == "lesson_ids":
                        lesson = check_lesson(db, context, identity)
                        course = check_course(db, context, lesson.course_id)
                        lines.append(f"课次：{lesson.title} · {course.name}" + (f" · {lesson.lesson_date}" if lesson.lesson_date else ""))
                    else:
                        from ...shared.models import CourseMaterial
                        from ..materials.processing import owned_material, material_read
                        material = db.scalar(select(CourseMaterial).where(CourseMaterial.id == identity))
                        if material is None or (context.lesson_id and material.lesson_id != context.lesson_id):
                            continue
                        check_course(db, context, material.course_id)
                        material = owned_material(db, material.course_id, identity, context.username)
                        state = material_read(db, material)
                        labels = {"stored": "未加入问答", "queued": "等待解析", "processing": "解析中", "indexing": "建立索引中", "ready": "可用于问答", "failed": "解析失败", "unsupported": "仅预览与下载"}
                        lines.append(f"课件：{material.filename} · {labels[state['processing_status']]}" + (" · 上一版本仍可用" if state["indexed"] and state["processing_status"] != "ready" else ""))
                except HTTPException:
                    continue
        return lines

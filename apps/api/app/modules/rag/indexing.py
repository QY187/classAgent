from ...core.visibility import visible_get
import json
import re

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ...core.embeddings import embed_texts
from ...shared.models import DocumentChunk, Lesson, LessonSummary, TranscriptSegment, new_id


TARGET_CHARS = 520
MIN_CHARS = 220
MAX_CHARS = 820
OVERLAP_CHARS = 100
PAUSE_BREAK_MS = 1200
SENTENCE_END = re.compile(r"(?<=[。！？!?；;])\s*|(?<=[：:])(?=\s*(?:下面|接下来|首先|然后|最后|总结|注意))")
TOPIC_START = re.compile(r"^(?:下面|接下来|我们来|现在来看|总结一下|注意|重点是|另一个问题)")


def _units(segments: list[TranscriptSegment]) -> list[dict]:
    """把 ASR 片段拆成带时间和来源的句子单元；长句再做安全硬切。"""
    units: list[dict] = []
    previous_end = None
    for segment in segments:
        text = " ".join(str(segment.text or "").split()).strip()
        if not text:
            continue
        pause = previous_end is not None and segment.start_ms - previous_end >= PAUSE_BREAK_MS
        pieces = [piece.strip() for piece in SENTENCE_END.split(text) if piece.strip()] or [text]
        for piece in pieces:
            # 没有标点的长 ASR 片段按词边界不可得时按字符切，并保留来源 ID。
            if len(piece) <= MAX_CHARS:
                units.append({"text": piece, "speaker": segment.speaker, "start_ms": segment.start_ms,
                              "end_ms": segment.end_ms, "id": segment.id, "hard_break": pause})
                pause = False
                continue
            for start in range(0, len(piece), MAX_CHARS - OVERLAP_CHARS):
                part = piece[start:start + MAX_CHARS]
                units.append({"text": part, "speaker": segment.speaker, "start_ms": segment.start_ms,
                              "end_ms": segment.end_ms, "id": segment.id, "hard_break": pause or start > 0})
                pause = False
        previous_end = segment.end_ms
    return units


def make_chunks(segments: list[TranscriptSegment], summary_content: str | None = None) -> list[dict]:
    """按句子、停顿、说话人和主题边界生成带轻微重叠的语义块。"""
    chunks: list[dict] = []
    window: list[dict] = []
    size = 0

    def emit() -> None:
        nonlocal window, size
        if not window:
            return
        chunks.append({
            "kind": "transcript",
            "content": "\n".join(f"{item['speaker']}：{item['text']}" for item in window),
            "start_ms": window[0]["start_ms"], "end_ms": window[-1]["end_ms"],
            "source_segment_ids": list(dict.fromkeys(item["id"] for item in window)),
        })
        # 保留末尾上下文，避免定义和结论被切到不同块。
        tail: list[dict] = []
        tail_size = 0
        for item in reversed(window):
            if tail_size + len(item["text"]) > OVERLAP_CHARS and tail:
                break
            tail.insert(0, item)
            tail_size += len(item["text"])
        window = tail
        size = tail_size

    for item in _units(segments):
        topic_break = bool(TOPIC_START.match(item["text"]))
        speaker_break = bool(window and item["speaker"] != window[-1]["speaker"])
        forced_break = bool(window and (item["hard_break"] or speaker_break or topic_break))
        if forced_break and size >= MIN_CHARS:
            emit()
        if window and size + len(item["text"]) > MAX_CHARS:
            emit()
        window.append(item)
        size += len(item["text"])
        if size >= TARGET_CHARS:
            emit()
    if size >= MIN_CHARS or not chunks:
        emit()

    if summary_content:
        try:
            summary = json.loads(summary_content)
        except (ValueError, TypeError):
            summary = None
        if isinstance(summary, dict):
            for value in summary.values():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    indexes = item.get("source_indexes", [])
                    sources = [segments[i - 1] for i in indexes if isinstance(i, int) and 1 <= i <= len(segments)] if isinstance(indexes, list) else []
                    body = "；".join(str(part) for key, part in item.items() if key not in {"source_indexes", "time_range"} and isinstance(part, str) and part.strip())
                    if sources and body:
                        chunks.append({
                            "kind": "summary", "content": body[:1200],
                            "start_ms": min(s.start_ms for s in sources),
                            "end_ms": max(s.end_ms for s in sources),
                            "source_segment_ids": [s.id for s in sources],
                        })
    return chunks


def _render(items: list[dict], *, kind: str, level: str, index: int = 0, parent_key: str | None = None) -> dict:
    return {"id": new_id(), "kind": kind, "chunk_level": level, "chunk_index": index,
            "parent_key": parent_key,
            "content": "\n".join(f"{item['speaker']}：{item['text']}" for item in items),
            "start_ms": items[0]["start_ms"], "end_ms": items[-1]["end_ms"],
            "source_segment_ids": list(dict.fromkeys(item["id"] for item in items))}


def build_hierarchy(chunks: list[dict], segments: list[TranscriptSegment] | None = None) -> list[dict]:
    """先按主题边界生成父块，再在每个父块内部切检索子块。"""
    if segments is None:
        # 保持调用方兼容：没有原始句子时只能从已有块退化构造。
        transcript = chunks
    else:
        transcript = _units(segments)
    result: list[dict] = []
    parents: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for item in transcript:
        topic_break = bool(current and (item.get("hard_break") or item["speaker"] != current[-1]["speaker"] or TOPIC_START.match(item["text"])))
        if current and ((topic_break and size >= 500) or size + len(item["text"]) > 1800):
            parents.append(current)
            current, size = [], 0
        current.append(item)
        size += len(item["text"])
    if current:
        parents.append(current)
    for parent_items in parents:
        parent_id = new_id()
        parent = _render(parent_items, kind="transcript", level="parent")
        parent["id"] = parent_id
        result.append(parent)
        child_window: list[dict] = []
        child_size = 0
        child_index = 0
        for item in parent_items:
            if child_window and child_size + len(item["text"]) > MAX_CHARS:
                result.append(_render(child_window, kind="transcript", level="child", index=child_index, parent_key=parent_id))
                child_index += 1
                tail = child_window[-1:]
                child_window, child_size = tail, sum(len(row["text"]) for row in tail)
            child_window.append(item)
            child_size += len(item["text"])
            if child_size >= TARGET_CHARS:
                result.append(_render(child_window, kind="transcript", level="child", index=child_index, parent_key=parent_id))
                child_index += 1
                tail = child_window[-1:]
                child_window, child_size = tail, sum(len(row["text"]) for row in tail)
        already_emitted_tail = len(child_window) == 1 and child_window[0] is parent_items[-1] and child_index > 0
        if child_window and (child_size >= MIN_CHARS or child_index == 0) and not already_emitted_tail:
            result.append(_render(child_window, kind="transcript", level="child", index=child_index, parent_key=parent_id))
    result.extend(item | {"id": new_id(), "chunk_level": "summary", "chunk_index": index, "parent_key": None}
                  for index, item in enumerate(item for item in chunks if item["kind"] != "transcript"))
    return result


def reindex_lesson(db: Session, lesson_id: str) -> int:
    lesson = visible_get(db, Lesson, lesson_id)
    if lesson is None:
        return 0
    # 同一课次的重复任务顺序执行，防止旧任务覆盖新索引。
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lesson_id})
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms, TranscriptSegment.id)))
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    chunks = build_hierarchy(make_chunks(segments, summary.content if summary and summary.status in {"completed", "edited"} else None), segments)
    vectors = embed_texts([chunk["content"] for chunk in chunks])
    db.execute(delete(DocumentChunk).where(DocumentChunk.lesson_id == lesson_id))
    ids = {chunk.get("id", new_id()): chunk for chunk in chunks}
    parent_ids = {key: value["id"] for key, value in ids.items() if value.get("chunk_level") == "parent"}
    for chunk, vector in zip(chunks, vectors):
        identity = chunk.get("id", new_id())
        db.add(DocumentChunk(
            id=identity,
            course_id=lesson.course_id, lesson_id=lesson_id,
            kind=chunk["kind"], content=chunk["content"],
            start_ms=chunk["start_ms"], end_ms=chunk["end_ms"],
            source_segment_ids=json.dumps(chunk["source_segment_ids"]), embedding=vector,
            parent_id=parent_ids.get(chunk.get("parent_key")),
            chunk_level=chunk.get("chunk_level", "child"), chunk_index=chunk.get("chunk_index", 0),
        ))
    db.commit()
    return len(chunks)

import json

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ...core.embeddings import embed_texts
from ...shared.models import DocumentChunk, Lesson, LessonSummary, TranscriptSegment


def make_chunks(segments: list[TranscriptSegment], summary_content: str | None = None) -> list[dict]:
    chunks: list[dict] = []
    window: list[TranscriptSegment] = []
    size = 0

    def flush() -> None:
        nonlocal window, size
        if window:
            chunks.append({
                "kind": "transcript",
                "content": "\n".join(f"{segment.speaker}：{segment.text}" for segment in window),
                "start_ms": window[0].start_ms,
                "end_ms": window[-1].end_ms,
                "source_segment_ids": [segment.id for segment in window],
            })
            window, size = [], 0

    for segment in segments:
        if not segment.text.strip():
            continue
        if len(segment.text) > 700:
            flush()
            for start in range(0, len(segment.text), 600):
                chunks.append({
                    "kind": "transcript", "content": f"{segment.speaker}：{segment.text[start:start + 600]}",
                    "start_ms": segment.start_ms, "end_ms": segment.end_ms,
                    "source_segment_ids": [segment.id],
                })
            continue
        if window and size + len(segment.text) > 700:
            flush()
        window.append(segment)
        size += len(segment.text)
        if size >= 700:
            flush()
    flush()

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


def reindex_lesson(db: Session, lesson_id: str) -> int:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        return 0
    # 同一课次的重复任务顺序执行，防止旧任务覆盖新索引。
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lesson_id})
    segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms, TranscriptSegment.id)))
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    chunks = make_chunks(segments, summary.content if summary and summary.status in {"completed", "edited"} else None)
    vectors = embed_texts([chunk["content"] for chunk in chunks])
    db.execute(delete(DocumentChunk).where(DocumentChunk.lesson_id == lesson_id))
    for chunk, vector in zip(chunks, vectors):
        db.add(DocumentChunk(
            course_id=lesson.course_id, lesson_id=lesson_id,
            kind=chunk["kind"], content=chunk["content"],
            start_ms=chunk["start_ms"], end_ms=chunk["end_ms"],
            source_segment_ids=json.dumps(chunk["source_segment_ids"]), embedding=vector,
        ))
    db.commit()
    return len(chunks)

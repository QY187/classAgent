from sqlalchemy import select
from sqlalchemy.orm import Session

from ...shared.models import Course, Lesson, LessonSummary, TranscriptSegment


def _snippet(text: str, query: str, width: int = 36) -> str:
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx < 0:
        return text[: width * 2]
    start = max(0, idx - width)
    end = min(len(text), idx + len(query) + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def search_all(db: Session, query: str) -> dict:
    pattern = f"%{query}%"
    courses = db.scalars(
        select(Course).where(Course.name.ilike(pattern)).order_by(Course.created_at.desc()).limit(20)
    ).all()
    lessons = db.scalars(
        select(Lesson).where(Lesson.title.ilike(pattern)).order_by(Lesson.created_at.desc()).limit(20)
    ).all()

    transcript_rows = db.execute(
        select(TranscriptSegment, Lesson, Course)
        .join(Lesson, TranscriptSegment.lesson_id == Lesson.id)
        .join(Course, Lesson.course_id == Course.id)
        .where(TranscriptSegment.text.ilike(pattern))
        .order_by(Lesson.created_at.desc(), TranscriptSegment.start_ms)
        .limit(30)
    ).all()

    summary_rows = db.execute(
        select(LessonSummary, Lesson, Course)
        .join(Lesson, LessonSummary.lesson_id == Lesson.id)
        .join(Course, Lesson.course_id == Course.id)
        .where(LessonSummary.content.ilike(pattern))
        .limit(15)
    ).all()

    return {
        "query": query,
        "courses": [{"id": course.id, "name": course.name, "semester": course.semester} for course in courses],
        "lessons": [
            {"id": lesson.id, "course_id": lesson.course_id, "title": lesson.title, "lesson_date": lesson.lesson_date}
            for lesson in lessons
        ],
        "transcript": [
            {
                "segment_id": segment.id,
                "lesson_id": lesson.id,
                "course_id": course.id,
                "lesson_title": lesson.title,
                "course_name": course.name,
                "speaker": segment.speaker,
                "start_ms": segment.start_ms,
                "text": segment.text,
                "snippet": _snippet(segment.text, query),
            }
            for segment, lesson, course in transcript_rows
        ],
        "summaries": [
            {"lesson_id": lesson.id, "course_id": course.id, "lesson_title": lesson.title, "course_name": course.name}
            for _summary, lesson, course in summary_rows
        ],
    }

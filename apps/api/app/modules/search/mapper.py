from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...shared.models import Course, Lesson, LessonSummary, ReviewCard, TranscriptSegment


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


def search_all(db: Session, query: str, owner_username: str, course_id: str | None = None, kind: str = "all") -> dict:
    pattern = f"%{query}%"
    owned = Course.owner_id == user_id_for_username(db, owner_username)
    scope = [owned, *([Course.id == course_id] if course_id else [])]
    courses = db.scalars(
        select(Course).where(*scope, Course.name.ilike(pattern)).order_by(Course.created_at.desc()).limit(20)
    ).all() if kind in ("all", "courses") else []
    lessons = db.scalars(
        select(Lesson).join(Course, Lesson.course_id == Course.id)
        .where(*scope, Lesson.title.ilike(pattern)).order_by(Lesson.created_at.desc()).limit(20)
    ).all() if kind in ("all", "lessons") else []

    transcript_rows = db.execute(
        select(TranscriptSegment, Lesson, Course)
        .join(Lesson, TranscriptSegment.lesson_id == Lesson.id)
        .join(Course, Lesson.course_id == Course.id)
        .where(*scope, TranscriptSegment.text.ilike(pattern))
        .order_by(Lesson.created_at.desc(), TranscriptSegment.start_ms)
        .limit(30)
    ).all() if kind in ("all", "transcript") else []

    summary_rows = db.execute(
        select(LessonSummary, Lesson, Course)
        .join(Lesson, LessonSummary.lesson_id == Lesson.id)
        .join(Course, Lesson.course_id == Course.id)
        .where(*scope, LessonSummary.content.ilike(pattern))
        .limit(15)
    ).all() if kind in ("all", "summaries") else []

    card_rows = db.execute(
        select(ReviewCard, Lesson, Course)
        .join(Lesson, ReviewCard.lesson_id == Lesson.id)
        .join(Course, Lesson.course_id == Course.id)
        .where(*scope, ReviewCard.title.ilike(pattern) | ReviewCard.body.ilike(pattern))
        .order_by(ReviewCard.created_at.desc())
        .limit(30)
    ).all() if kind in ("all", "review_cards") else []

    return {
        "query": query,
        "courses": [{"id": course.id, "name": course.name, "semester": course.semester} for course in courses],
        "lessons": [
            {"id": lesson.id, "course_id": lesson.course_id, "course_name": lesson.course.name, "title": lesson.title, "lesson_date": lesson.lesson_date}
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
        "review_cards": [
            {
                "id": card.id,
                "course_id": course.id,
                "course_name": course.name,
                "lesson_id": lesson.id,
                "lesson_title": lesson.title,
                "title": card.title,
                "snippet": _snippet(card.body, query),
            }
            for card, lesson, course in card_rows
        ],
    }

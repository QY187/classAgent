from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import LessonSummary, TranscriptSegment


def find_summary(db: Session, lesson_id: str) -> LessonSummary | None:
    return db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))


def has_transcript(db: Session, lesson_id: str) -> bool:
    return db.scalar(select(TranscriptSegment.id).where(TranscriptSegment.lesson_id == lesson_id).limit(1)) is not None

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...shared.models import TranscriptBookmark, TranscriptSegment
from ...shared.schemas import TranscriptBookmarkKind
from .service import get_lesson


def list_bookmarks(db: Session, lesson_id: str, username: str) -> list[TranscriptBookmark]:
    get_lesson(db, lesson_id, username)
    return list(db.scalars(
        select(TranscriptBookmark)
        .join(TranscriptSegment, TranscriptBookmark.segment_id == TranscriptSegment.id)
        .where(TranscriptSegment.lesson_id == lesson_id)
        .order_by(TranscriptSegment.start_ms, TranscriptSegment.id, TranscriptBookmark.kind)
    ))


def set_bookmark(
    db: Session, lesson_id: str, segment_id: str, kind: TranscriptBookmarkKind, username: str, *, enabled: bool,
) -> None:
    get_lesson(db, lesson_id, username)
    segment = db.scalar(select(TranscriptSegment).where(
        TranscriptSegment.id == segment_id,
        TranscriptSegment.lesson_id == lesson_id,
    ).with_for_update())
    if segment is None:
        raise HTTPException(status_code=404, detail="文字片段不存在")
    bookmark = db.get(TranscriptBookmark, (segment_id, kind))
    if enabled and bookmark is None:
        db.add(TranscriptBookmark(segment_id=segment_id, kind=kind))
    elif not enabled and bookmark is not None:
        db.delete(bookmark)
    db.commit()

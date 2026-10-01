import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ...shared.models import Course, Lesson, LessonSummary, ReviewCard, TranscriptSegment, now_utc
from .schemas import CardCreate, CardReview, CardUpdate


def _owned_lesson(db: Session, lesson_id: str, username: str) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or lesson.course.owner_username != username:
        raise HTTPException(status_code=404, detail="课次不存在")
    return lesson


def _owned_card(db: Session, card_id: str, username: str) -> ReviewCard:
    card = db.get(ReviewCard, card_id)
    if card is None or card.lesson.course.owner_username != username:
        raise HTTPException(status_code=404, detail="复习卡片不存在")
    return card


def serialize(card: ReviewCard) -> dict:
    return {
        "id": card.id,
        "course_id": card.course_id,
        "course_name": card.lesson.course.name,
        "lesson_id": card.lesson_id,
        "lesson_title": card.lesson.title,
        "card_type": card.card_type,
        "title": card.title,
        "body": card.body,
        "status": card.status,
        "source_segment_id": card.source_segment_id,
        "source_start_ms": card.source_start_ms,
        "source_excerpt": card.source_excerpt,
        "created_at": card.created_at,
    }


def list_lesson_cards(db: Session, lesson_id: str, username: str) -> list[dict]:
    _owned_lesson(db, lesson_id, username)
    cards = db.scalars(select(ReviewCard).where(ReviewCard.lesson_id == lesson_id).order_by(ReviewCard.created_at.desc())).all()
    return [serialize(card) for card in cards]


def list_cards(db: Session, username: str) -> list[dict]:
    cards = db.scalars(
        select(ReviewCard)
        .join(ReviewCard.lesson).join(Lesson.course)
        .where(Course.owner_username == username)
        .options(joinedload(ReviewCard.lesson).joinedload(Lesson.course))
        .order_by(ReviewCard.created_at.desc())
    ).all()
    return [serialize(card) for card in cards]


def create_card(db: Session, lesson_id: str, payload: CardCreate, username: str) -> dict:
    lesson = _owned_lesson(db, lesson_id, username)
    segment = None
    if payload.source_segment_id:
        segment = db.get(TranscriptSegment, payload.source_segment_id)
        if segment is None or segment.lesson_id != lesson_id:
            raise HTTPException(status_code=400, detail="来源片段不属于该课次")
    card = ReviewCard(
        course_id=lesson.course_id, lesson_id=lesson_id, card_type=payload.card_type,
        title=payload.title.strip(), body=payload.body.strip(),
        source_segment_id=segment.id if segment else None,
        source_start_ms=segment.start_ms if segment else None,
        source_excerpt=segment.text if segment else None,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return serialize(card)


def create_from_summary(db: Session, lesson_id: str, username: str) -> dict[str, int]:
    lesson = _owned_lesson(db, lesson_id, username)
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    if summary is None or not summary.content:
        raise HTTPException(status_code=400, detail="请先生成智能纪要")
    try:
        content = json.loads(summary.content)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="当前纪要已编辑为文档，请手动创建复习卡片") from exc
    if not isinstance(content, dict):
        raise HTTPException(status_code=400, detail="纪要内容格式不正确")
    concepts = content.get("key_concepts") or []
    if not isinstance(concepts, list) or not concepts:
        raise HTTPException(status_code=400, detail="纪要中没有可生成的核心概念")

    segments = db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms)).all()
    existing = set(db.scalars(select(ReviewCard.origin_key).where(ReviewCard.lesson_id == lesson_id)).all())
    created = 0
    for concept in concepts:
        if not isinstance(concept, dict):
            continue
        term = str(concept.get("term") or "").strip()
        definition = str(concept.get("definition") or "").strip()
        indexes = concept.get("source_indexes") or []
        source_index = next((index for index in indexes if isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= len(segments)), None) if isinstance(indexes, list) else None
        if not term or not definition or source_index is None:
            continue
        origin_key = "concept:" + hashlib.sha256(term.encode("utf-8")).hexdigest()[:24]
        if origin_key in existing:
            continue
        source = segments[source_index - 1]
        importance = str(concept.get("importance") or "").strip()
        db.add(ReviewCard(
            course_id=lesson.course_id, lesson_id=lesson_id, card_type="concept",
            title=term[:200], body=(definition + (f"\n重要性：{importance}" if importance else ""))[:10000],
            origin_key=origin_key, source_segment_id=source.id,
            source_start_ms=source.start_ms, source_excerpt=source.text,
        ))
        existing.add(origin_key)
        created += 1
    db.commit()
    return {"created": created, "skipped": len(concepts) - created}


def update_card(db: Session, card_id: str, payload: CardUpdate, username: str) -> dict:
    card = _owned_card(db, card_id, username)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is not None:
            setattr(card, field, value.strip() if field in {"title", "body"} else value)
    db.commit()
    db.refresh(card)
    return serialize(card)


def review_card(db: Session, card_id: str, payload: CardReview, username: str) -> dict:
    card = _owned_card(db, card_id, username)
    card.status = payload.status
    card.last_reviewed_at = now_utc()
    db.commit()
    db.refresh(card)
    return serialize(card)


def delete_card(db: Session, card_id: str, username: str) -> None:
    card = _owned_card(db, card_id, username)
    db.delete(card)
    db.commit()

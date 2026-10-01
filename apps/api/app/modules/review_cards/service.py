from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ...shared.models import Course, Lesson, ReviewCard, TranscriptSegment, now_utc
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
        "next_review_at": card.next_review_at,
        "last_reviewed_at": card.last_reviewed_at,
        "created_at": card.created_at,
    }


def list_lesson_cards(db: Session, lesson_id: str, username: str) -> list[dict]:
    _owned_lesson(db, lesson_id, username)
    cards = db.scalars(select(ReviewCard).where(ReviewCard.lesson_id == lesson_id).order_by(ReviewCard.created_at.desc())).all()
    return [serialize(card) for card in cards]


def list_due_cards(db: Session, username: str) -> list[dict]:
    cards = db.scalars(
        select(ReviewCard)
        .join(ReviewCard.lesson).join(Lesson.course)
        .where(Course.owner_username == username, ReviewCard.next_review_at <= now_utc())
        .options(joinedload(ReviewCard.lesson).joinedload(Lesson.course))
        .order_by(ReviewCard.next_review_at, ReviewCard.created_at)
        .limit(100)
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
    reviewed_at = now_utc()
    card.status = payload.status
    card.last_reviewed_at = reviewed_at
    card.next_review_at = reviewed_at + {"new": timedelta(0), "review": timedelta(days=1), "mastered": timedelta(days=7)}[payload.status]
    db.commit()
    db.refresh(card)
    return serialize(card)


def delete_card(db: Session, card_id: str, username: str) -> None:
    card = _owned_card(db, card_id, username)
    db.delete(card)
    db.commit()

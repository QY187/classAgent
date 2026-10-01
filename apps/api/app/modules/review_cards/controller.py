from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from . import service
from .schemas import CardCreate, CardRead, CardReview, CardUpdate


router = APIRouter(tags=["review-cards"])


@router.get("/lessons/{lesson_id}/review-cards", response_model=list[CardRead])
def list_lesson_cards(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_lesson_cards(db, lesson_id, username)


@router.get("/review-cards", response_model=list[CardRead])
def list_cards(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_cards(db, username)


@router.post("/lessons/{lesson_id}/review-cards", response_model=CardRead, status_code=201)
def create_card(lesson_id: str, payload: CardCreate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.create_card(db, lesson_id, payload, username)


@router.post("/lessons/{lesson_id}/review-cards/from-summary")
def create_from_summary(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.create_from_summary(db, lesson_id, username)


@router.patch("/review-cards/{card_id}", response_model=CardRead)
def update_card(card_id: str, payload: CardUpdate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_card(db, card_id, payload, username)


@router.post("/review-cards/{card_id}/review", response_model=CardRead)
def review_card(card_id: str, payload: CardReview, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.review_card(db, card_id, payload, username)


@router.delete("/review-cards/{card_id}", status_code=204)
def delete_card(card_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_card(db, card_id, username)

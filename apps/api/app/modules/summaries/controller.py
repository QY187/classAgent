from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...schemas import SummaryRead
from . import service


router = APIRouter(tags=["summaries"])


@router.get("/lessons/{lesson_id}/summary", response_model=SummaryRead)
def get_summary(lesson_id: str, db: Session = Depends(get_db)):
    return service.get_summary(db, lesson_id)


@router.post("/lessons/{lesson_id}/summary", response_model=SummaryRead, status_code=202)
def request_summary(lesson_id: str, db: Session = Depends(get_db)):
    return service.request_summary(db, lesson_id)

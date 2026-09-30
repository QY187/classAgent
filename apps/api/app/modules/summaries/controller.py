from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from ...shared.schemas import SummaryRead, SummaryUpdate
from . import service


router = APIRouter(tags=["summaries"], dependencies=[Depends(get_current_user)])


@router.get("/lessons/{lesson_id}/summary", response_model=SummaryRead)
def get_summary(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_summary(db, lesson_id, username)


@router.post("/lessons/{lesson_id}/summary", response_model=SummaryRead, status_code=202)
def request_summary(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.request_summary(db, lesson_id, username)


@router.put("/lessons/{lesson_id}/summary", response_model=SummaryRead)
def update_summary(lesson_id: str, payload: SummaryUpdate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_summary_content(db, lesson_id, payload.content, username)

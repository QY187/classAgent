from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import get_db
from ...models import Lesson, LessonSummary, TranscriptSegment
from ...schemas import SummaryRead
from ...tasks import generate_summary


router = APIRouter(tags=["summaries"])


@router.get("/lessons/{lesson_id}/summary", response_model=SummaryRead)
def get_summary(lesson_id: str, db: Session = Depends(get_db)) -> LessonSummary:
    if db.get(Lesson, lesson_id) is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    if summary is None:
        raise HTTPException(status_code=404, detail="该课次暂无智能纪要")
    return summary


@router.post("/lessons/{lesson_id}/summary", response_model=SummaryRead, status_code=202)
def request_summary(lesson_id: str, db: Session = Depends(get_db)) -> LessonSummary:
    if db.get(Lesson, lesson_id) is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    if db.scalar(select(TranscriptSegment.id).where(TranscriptSegment.lesson_id == lesson_id).limit(1)) is None:
        raise HTTPException(status_code=400, detail="请先完成文字记录，再生成智能纪要")
    summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson_id))
    if summary is None:
        summary = LessonSummary(lesson_id=lesson_id, provider=get_settings().summary_provider)
        db.add(summary)
    summary.status = "queued"
    summary.error_message = None
    db.commit()
    db.refresh(summary)
    generate_summary.delay(lesson_id)
    return summary

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...shared.schemas import JobRead, LessonRead, TranscriptSegmentRead
from . import service


router = APIRouter(tags=["lessons"])


@router.get("/lessons/{lesson_id}", response_model=LessonRead)
def get_lesson(lesson_id: str, db: Session = Depends(get_db)):
    return service.get_lesson(db, lesson_id)


@router.post("/lessons/{lesson_id}/audio", response_model=JobRead, status_code=202)
def upload_audio(lesson_id: str, file: UploadFile = File(...), browser_transcript: str | None = Form(None), db: Session = Depends(get_db)):
    return service.upload_audio(db, lesson_id, file, browser_transcript)


@router.get("/lessons/{lesson_id}/jobs/latest", response_model=JobRead)
def latest_job(lesson_id: str, db: Session = Depends(get_db)):
    return service.latest_job(db, lesson_id)


@router.get("/lessons/{lesson_id}/transcript", response_model=list[TranscriptSegmentRead])
def get_transcript(lesson_id: str, db: Session = Depends(get_db)):
    return service.get_transcript(db, lesson_id)

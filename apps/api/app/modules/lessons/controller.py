import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ...core.db import get_db
from ...core.deps import get_current_user, get_current_user_flexible
from ...shared.schemas import AudioMeta, JobRead, LessonRead, SpeakerAliasRead, TranscriptMerge, TranscriptSegmentRead, TranscriptSegmentUpdate
from . import service


router = APIRouter(tags=["lessons"], dependencies=[Depends(get_current_user)])
audio_router = APIRouter(tags=["lessons"], dependencies=[Depends(get_current_user_flexible)])


@router.get("/lessons/{lesson_id}", response_model=LessonRead)
def get_lesson(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_lesson(db, lesson_id, username)


@router.post("/lessons/{lesson_id}/audio", response_model=JobRead, status_code=202)
def upload_audio(lesson_id: str, file: UploadFile = File(...), browser_transcript: str | None = Form(None), username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.upload_audio(db, lesson_id, file, browser_transcript, username)


@router.get("/lessons/{lesson_id}/jobs/latest", response_model=JobRead)
def latest_job(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.latest_job(db, lesson_id, username)


@router.get("/lessons/{lesson_id}/transcript", response_model=list[TranscriptSegmentRead])
def get_transcript(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_transcript(db, lesson_id, username)


@audio_router.get("/lessons/{lesson_id}/audio/meta", response_model=AudioMeta)
def get_audio_meta(lesson_id: str, username: str = Depends(get_current_user_flexible), db: Session = Depends(get_db)):
    return service.get_audio_meta(db, lesson_id, username)


@audio_router.get("/lessons/{lesson_id}/audio")
def stream_audio(lesson_id: str, username: str = Depends(get_current_user_flexible), db: Session = Depends(get_db)):
    audio, path, must_remove = service.get_audio_filepath(db, lesson_id, username)
    return FileResponse(
        path,
        media_type=audio.content_type,
        filename=audio.filename,
        headers={"Accept-Ranges": "bytes"},
        background=BackgroundTask(os.unlink, path) if must_remove else None,
    )


@router.get("/lessons/{lesson_id}/speakers", response_model=list[SpeakerAliasRead])
def get_speakers(lesson_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_speakers(db, lesson_id, username)


@router.put("/lessons/{lesson_id}/speakers", response_model=list[SpeakerAliasRead])
def put_speakers(lesson_id: str, payload: dict[str, str], username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_speakers(db, lesson_id, payload, username)


@router.post("/lessons/{lesson_id}/transcript/merge", response_model=TranscriptSegmentRead)
def merge_segments(lesson_id: str, payload: TranscriptMerge, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.merge_segments(db, lesson_id, payload.first_id, payload.second_id, username)


@router.patch("/lessons/{lesson_id}/transcript/{segment_id}", response_model=TranscriptSegmentRead)
def update_transcript_segment(lesson_id: str, segment_id: str, payload: TranscriptSegmentUpdate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_transcript_segment(db, lesson_id, segment_id, payload.text, username)

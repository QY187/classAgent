from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine, get_db
from .models import AudioFile, Course, Lesson, ProcessingJob, TranscriptSegment
from .schemas import CourseCreate, CourseRead, JobRead, LessonCreate, LessonRead, TranscriptSegmentRead
from .storage import upload_file
from .tasks import process_audio


app = FastAPI(title="ClassAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/courses", response_model=CourseRead, status_code=201)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    course = Course(name=payload.name, semester=payload.semester)
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@app.get("/courses", response_model=list[CourseRead])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(db.scalars(select(Course).order_by(Course.created_at.desc())))


@app.post("/courses/{course_id}/lessons", response_model=LessonRead, status_code=201)
def create_lesson(course_id: str, payload: LessonCreate, db: Session = Depends(get_db)) -> Lesson:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    lesson = Lesson(course_id=course_id, title=payload.title, lesson_date=payload.lesson_date)
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


@app.get("/courses/{course_id}/lessons", response_model=list[LessonRead])
def list_lessons(course_id: str, db: Session = Depends(get_db)) -> list[Lesson]:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return list(db.scalars(select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.created_at.desc())))


@app.get("/lessons/{lesson_id}", response_model=LessonRead)
def get_lesson(lesson_id: str, db: Session = Depends(get_db)) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    return lesson


@app.post("/lessons/{lesson_id}/audio", response_model=JobRead, status_code=202)
def upload_audio(lesson_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)) -> ProcessingJob:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    if not file.content_type or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="请上传音频文件")

    object_key = f"lessons/{lesson_id}/{uuid4()}-{Path(file.filename or 'audio').name}"
    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    upload_file(object_key, file.file, size_bytes, file.content_type)
    audio = AudioFile(
        lesson_id=lesson_id,
        filename=file.filename or "audio",
        content_type=file.content_type,
        object_key=object_key,
        size_bytes=size_bytes,
    )
    job = ProcessingJob(lesson_id=lesson_id, stage="queued", progress=0)
    lesson.status = "queued"
    db.add_all([audio, job])
    db.commit()
    db.refresh(job)
    process_audio.delay(job.id)
    return job

@app.get("/lessons/{lesson_id}/jobs/latest", response_model=JobRead)
def latest_job(lesson_id: str, db: Session = Depends(get_db)) -> ProcessingJob:
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.lesson_id == lesson_id).order_by(ProcessingJob.created_at.desc()))
    if job is None:
        raise HTTPException(status_code=404, detail="该课次暂无处理任务")
    return job


@app.get("/lessons/{lesson_id}/transcript", response_model=list[TranscriptSegmentRead])
def get_transcript(lesson_id: str, db: Session = Depends(get_db)) -> list[TranscriptSegment]:
    return list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms)))

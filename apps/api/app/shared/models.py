from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    semester: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    lesson_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    course: Mapped[Course] = relationship(back_populates="lessons")
    audio_files: Mapped[list["AudioFile"]] = relationship(back_populates="lesson", cascade="all, delete-orphan")
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="lesson", cascade="all, delete-orphan")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="lesson", cascade="all, delete-orphan")


class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    lesson: Mapped[Lesson] = relationship(back_populates="audio_files")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    lesson: Mapped[Lesson] = relationship(back_populates="jobs")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    speaker: Mapped[str] = mapped_column(String(100), default="说话人 1")
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="mock")
    lesson: Mapped[Lesson] = relationship(back_populates="transcript_segments")


class LessonSummary(Base):
    __tablename__ = "lesson_summaries"
    __table_args__ = (UniqueConstraint("lesson_id", name="uq_lesson_summaries_lesson_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), default="dashscope")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    lesson: Mapped[Lesson] = relationship()

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import AudioFile, Lesson, ProcessingJob, TranscriptSegment


def find_lesson(db: Session, lesson_id: str) -> Lesson | None:
    return db.get(Lesson, lesson_id)


def clear_transcript(db: Session, lesson_id: str) -> None:
    from sqlalchemy import delete

    db.execute(delete(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id))


def save_audio_job(db: Session, audio: AudioFile, job: ProcessingJob, lesson: Lesson) -> ProcessingJob:
    lesson.status = "queued"
    db.add_all([audio, job])
    db.commit()
    db.refresh(job)
    return job


def find_latest_job(db: Session, lesson_id: str) -> ProcessingJob | None:
    return db.scalar(select(ProcessingJob).where(ProcessingJob.lesson_id == lesson_id).order_by(ProcessingJob.created_at.desc()))


def find_transcript(db: Session, lesson_id: str) -> list[TranscriptSegment]:
    return list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms)))

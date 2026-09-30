from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...shared.models import AudioFile, Lesson, ProcessingJob, SpeakerAlias, TranscriptRevision, TranscriptSegment


def find_lesson(db: Session, lesson_id: str) -> Lesson | None:
    return db.get(Lesson, lesson_id)


def clear_transcript(db: Session, lesson_id: str) -> None:
    db.execute(delete(TranscriptRevision).where(TranscriptRevision.segment_id.in_(
        select(TranscriptSegment.id).where(TranscriptSegment.lesson_id == lesson_id)
    )))
    db.execute(delete(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id))


def save_audio_job(db: Session, audio: AudioFile, job: ProcessingJob, lesson: Lesson) -> ProcessingJob:
    db.add_all([audio, job])
    db.commit()
    db.refresh(job)
    return job


def find_latest_job(db: Session, lesson_id: str) -> ProcessingJob | None:
    return db.scalar(select(ProcessingJob).where(ProcessingJob.lesson_id == lesson_id).order_by(ProcessingJob.created_at.desc()))


def find_transcript(db: Session, lesson_id: str) -> list[TranscriptSegment]:
    return list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson_id).order_by(TranscriptSegment.start_ms)))


def find_latest_audio(db: Session, lesson_id: str) -> AudioFile | None:
    return db.scalar(select(AudioFile).where(AudioFile.lesson_id == lesson_id).order_by(AudioFile.created_at.desc()))


def find_speaker_aliases(db: Session, lesson_id: str) -> list[SpeakerAlias]:
    return list(db.scalars(select(SpeakerAlias).where(SpeakerAlias.lesson_id == lesson_id)))


def replace_speaker_aliases(db: Session, lesson_id: str, aliases: dict[str, str]) -> None:
    db.execute(delete(SpeakerAlias).where(SpeakerAlias.lesson_id == lesson_id))
    for raw_label, display_name in aliases.items():
        db.add(SpeakerAlias(lesson_id=lesson_id, raw_label=raw_label, display_name=display_name))
    db.commit()


def merge_transcript_segments(db: Session, lesson_id: str, first_id: str, second_id: str) -> TranscriptSegment:
    first = db.get(TranscriptSegment, first_id)
    second = db.get(TranscriptSegment, second_id)
    if first is None or second is None or first.lesson_id != lesson_id or second.lesson_id != lesson_id:
        raise ValueError("文字片段不存在或不属于该课次")
    ordered = sorted([first, second], key=lambda segment: segment.start_ms)
    earlier, later = ordered
    earlier.text = f"{earlier.text or ''}{later.text or ''}"
    earlier.end_ms = later.end_ms
    db.delete(later)
    db.commit()
    db.refresh(earlier)
    return earlier

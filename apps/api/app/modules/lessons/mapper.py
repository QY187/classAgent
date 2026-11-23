from ...core.visibility import visible_get
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...shared.models import AudioFile, Lesson, ProcessingJob, SpeakerAlias, TranscriptBookmark, TranscriptRevision, TranscriptSegment


def find_lesson(db: Session, lesson_id: str) -> Lesson | None:
    return visible_get(db, Lesson, lesson_id)


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
    return db.scalar(select(ProcessingJob).where(ProcessingJob.lesson_id == lesson_id).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc()))


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
    segments = {segment.id: segment for segment in db.scalars(select(TranscriptSegment).where(
        TranscriptSegment.id.in_((first_id, second_id)),
        TranscriptSegment.lesson_id == lesson_id,
    ).order_by(TranscriptSegment.id).with_for_update())}
    if len(segments) != 2:
        raise ValueError("文字片段不存在或不属于该课次")
    earlier, later = sorted([segments[first_id], segments[second_id]], key=lambda segment: segment.start_ms)
    marks = list(db.scalars(select(TranscriptBookmark).where(TranscriptBookmark.segment_id.in_(segments))))
    earlier_kinds = {mark.kind for mark in marks if mark.segment_id == earlier.id}
    for mark in marks:
        if mark.segment_id == later.id and mark.kind not in earlier_kinds:
            db.add(TranscriptBookmark(segment_id=earlier.id, kind=mark.kind))
    earlier.text = f"{earlier.text or ''}{later.text or ''}"
    earlier.end_ms = later.end_ms
    db.delete(later)
    return earlier

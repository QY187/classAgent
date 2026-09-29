import io
import json
import os
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["DASHSCOPE_API_KEY"] = "test-key"

from fastapi import UploadFile  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.modules.lessons.service import update_transcript_segment, upload_audio  # noqa: E402
from app.infrastructure.asr import TranscriptResult  # noqa: E402
from app.infrastructure.tasks import process_audio  # noqa: E402
from app.shared.models import Course, Lesson, LessonSummary, TranscriptRevision, TranscriptSegment  # noqa: E402


class BrowserTranscriptUploadTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        course = Course(name="测试课程")
        self.lesson = Lesson(course=course, title="测试课次")
        self.db.add(self.lesson)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def upload(self, transcript=None):
        audio = UploadFile(
            filename="lesson.webm",
            file=io.BytesIO(b"audio data"),
            headers=Headers({"content-type": "audio/webm"}),
        )
        with patch("app.modules.lessons.service.upload_file"), patch(
            "app.infrastructure.tasks.generate_summary.delay"
        ) as summary_task, patch("app.infrastructure.tasks.process_audio.delay") as asr_task:
            job = upload_audio(self.db, self.lesson.id, audio, transcript)
        return job, summary_task, asr_task

    def test_browser_text_is_saved_without_audio_transcription_task(self):
        transcript = json.dumps([{"start_ms": 0, "end_ms": 1200, "text": "课堂开始。"}])
        job, summary_task, asr_task = self.upload(transcript)

        self.assertEqual((job.stage, job.progress, self.lesson.status), ("completed", 100, "completed"))
        segments = self.db.scalars(select(TranscriptSegment)).all()
        self.assertEqual([(item.text, item.source) for item in segments], [("课堂开始。", "browser")])
        self.assertEqual(self.db.scalar(select(LessonSummary)).status, "queued")
        summary_task.assert_called_once_with(self.lesson.id)
        asr_task.assert_not_called()

    def test_audio_only_upload_queues_file_transcription(self):
        job, summary_task, asr_task = self.upload()

        self.assertEqual((job.stage, self.lesson.status), ("queued", "queued"))
        self.assertEqual(self.db.scalars(select(TranscriptSegment)).all(), [])
        self.assertIsNone(self.db.scalar(select(LessonSummary)))
        summary_task.assert_not_called()
        asr_task.assert_called_once()
        self.assertEqual(asr_task.call_args.args[0], job.id)

    def test_worker_saves_paraformer_result(self):
        job, _, asr_task = self.upload()
        object_key = asr_task.call_args.args[1]
        with patch("app.core.db.SessionLocal", sessionmaker(bind=self.engine)), patch(
            "app.infrastructure.tasks.materialize_file", return_value=("audio.webm", False)
        ), patch(
            "app.infrastructure.tasks.transcribe_file",
            return_value=[TranscriptResult("说话人 1", 100, 900, "上传文件的文字。")],
        ), patch("app.infrastructure.tasks.generate_summary.delay") as summary_task:
            process_audio(job.id, object_key)

        self.db.expire_all()
        self.assertEqual((job.stage, job.progress, self.lesson.status), ("completed", 100, "completed"))
        segment = self.db.scalar(select(TranscriptSegment))
        self.assertEqual((segment.text, segment.source), ("上传文件的文字。", "paraformer"))
        summary_task.assert_called_once_with(self.lesson.id)

    def test_correct_transcript_preserves_revision_and_invalidates_summary(self):
        segment = TranscriptSegment(lesson_id=self.lesson.id, speaker="说话人 1", start_ms=0, end_ms=1000, text="错误词", source="paraformer")
        summary = LessonSummary(lesson_id=self.lesson.id, status="completed", content='{"overview":"旧纪要"}')
        self.db.add_all([segment, summary])
        self.db.commit()

        updated = update_transcript_segment(self.db, self.lesson.id, segment.id, "  正确词  ")

        self.assertEqual((updated.text, updated.source), ("正确词", "manual"))
        revision = self.db.scalar(select(TranscriptRevision))
        self.assertEqual((revision.previous_text, revision.updated_text, revision.previous_source), ("错误词", "正确词", "paraformer"))
        self.assertEqual((summary.status, summary.content), ("stale", None))

        update_transcript_segment(self.db, self.lesson.id, segment.id, "正确词")
        self.assertEqual(len(self.db.scalars(select(TranscriptRevision)).all()), 1)

    def test_correct_transcript_rejects_blank_and_other_lesson(self):
        segment = TranscriptSegment(lesson_id=self.lesson.id, speaker="说话人 1", start_ms=0, end_ms=1000, text="原文")
        self.db.add(segment)
        self.db.commit()

        with self.assertRaises(HTTPException) as blank:
            update_transcript_segment(self.db, self.lesson.id, segment.id, "   ")
        self.assertEqual(blank.exception.status_code, 400)
        with self.assertRaises(HTTPException) as wrong_lesson:
            update_transcript_segment(self.db, "another-lesson", segment.id, "新文字")
        self.assertEqual(wrong_lesson.exception.status_code, 404)
        self.assertEqual(segment.text, "原文")

    def test_reupload_clears_old_revisions(self):
        segment = TranscriptSegment(lesson_id=self.lesson.id, speaker="说话人 1", start_ms=0, end_ms=1000, text="原文")
        self.db.add(segment)
        self.db.commit()
        update_transcript_segment(self.db, self.lesson.id, segment.id, "修正")

        self.upload(json.dumps([{"start_ms": 0, "end_ms": 1000, "text": "新录音"}]))

        self.assertEqual(self.db.scalars(select(TranscriptRevision)).all(), [])
        self.assertEqual([item.text for item in self.db.scalars(select(TranscriptSegment)).all()], ["新录音"])


if __name__ == "__main__":
    unittest.main()

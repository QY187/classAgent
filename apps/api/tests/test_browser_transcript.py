import io
import json
import os
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi import UploadFile  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from starlette.datastructures import Headers  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.modules.lessons.service import upload_audio  # noqa: E402
from app.shared.models import Course, Lesson, LessonSummary, TranscriptSegment  # noqa: E402


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
        ) as summary_task:
            job = upload_audio(self.db, self.lesson.id, audio, transcript)
        return job, summary_task

    def test_browser_text_is_saved_without_audio_transcription_task(self):
        transcript = json.dumps([{"start_ms": 0, "end_ms": 1200, "text": "课堂开始。"}])
        job, summary_task = self.upload(transcript)

        self.assertEqual((job.stage, job.progress, self.lesson.status), ("completed", 100, "completed"))
        segments = self.db.scalars(select(TranscriptSegment)).all()
        self.assertEqual([(item.text, item.source) for item in segments], [("课堂开始。", "browser")])
        self.assertEqual(self.db.scalar(select(LessonSummary)).status, "queued")
        summary_task.assert_called_once_with(self.lesson.id)

    def test_audio_only_upload_does_not_create_mock_text(self):
        job, summary_task = self.upload()

        self.assertEqual((job.stage, self.lesson.status), ("completed", "audio_only"))
        self.assertEqual(self.db.scalars(select(TranscriptSegment)).all(), [])
        self.assertIsNone(self.db.scalar(select(LessonSummary)))
        summary_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()

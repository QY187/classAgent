import unittest
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
import test_home_overview as fixtures
from app.shared.models import Lesson, AudioFile, ProcessingJob, ChatConversation, ChatMessage, TranscriptSegment, AgentAction
from app.modules.lessons.retry import prepare_retry, dispatch_pending_retries
from app.modules.chat.retry_actions import actions_for_message, retry_requested
from app.modules.agent.schemas import RetryTranscriptionArguments


class RetryTest(unittest.TestCase):
    setUp = fixtures.HomeOverviewTest.setUp
    tearDown = fixtures.HomeOverviewTest.tearDown

    def seed(self):
        self.db.add(Lesson(id="l", course_id="c", title="第三讲", status="failed"))
        self.db.flush()
        self.db.add_all([ProcessingJob(id="old", lesson_id="l", stage="failed"),
            AudioFile(id="audio", lesson_id="l", filename="a.wav", content_type="audio/wav", object_key="a", size_bytes=3),
            ChatConversation(id="chat", user_id="u", course_id="c", generation_token="token")])
        self.db.flush()
        self.db.add(ChatMessage(id="msg", conversation_id="chat", position=1, request_id="request", role="user", status="pending", content="帮我重试第三讲的转写"))
        self.db.commit()

    def test_authorization_boundary(self):
        for text in ["怎么重试第三讲的转写", "不要重试第三讲的转写", "老师说重试第三讲的转写", "如果重试第三讲会怎样", "解释重试第三讲的转写", "重试第三讲转写可以吗"]:
            self.assertFalse(retry_requested(text), text)
        self.assertTrue(retry_requested("帮我重试第三讲的转写"))

    def test_action_idempotency_queue_failure_recovery_and_worker_redelivery(self):
        self.seed()
        from app.infrastructure.tasks import process_audio
        with patch("app.core.config.get_settings", return_value=SimpleNamespace(dashscope_api_key="configured")), patch("app.infrastructure.tasks.process_audio.apply_async", side_effect=RuntimeError("queue down")):
            action = actions_for_message(self.db, "chat", "owner", "msg", "token", "帮我重试第三讲的转写")["retry_transcription"]
            result = action(RetryTranscriptionArguments(lesson_id="l"))
            again = action(RetryTranscriptionArguments(lesson_id="l"))
            self.assertEqual(result["job_id"], again["job_id"])
            self.assertEqual(len(self.db.scalars(select(ProcessingJob)).all()), 2)
            self.assertEqual(len(self.db.scalars(select(AgentAction)).all()), 1)
        with patch("app.infrastructure.tasks.process_audio.apply_async") as send:
            self.assertEqual(dispatch_pending_retries(self.db), 1)
            send.assert_called_once()
        from app.infrastructure.tasks import process_audio
        from app.infrastructure.asr import TranscriptResult
        with patch("app.core.db.SessionLocal", sessionmaker(bind=self.engine)), patch("app.infrastructure.tasks.materialize_file", return_value=("a.wav",False)), patch("app.infrastructure.tasks.transcribe_file", return_value=[TranscriptResult("说话人",0,100,"原文")]) as transcribe, patch("app.infrastructure.tasks.generate_summary.delay"), patch("app.infrastructure.tasks.reindex_lesson.delay"):
            process_audio(result["job_id"], "a")
            process_audio(result["job_id"], "a")
            transcribe.assert_called_once()
        self.db.expire_all()
        self.assertEqual(dispatch_pending_retries(self.db), 0)

    def test_no_overwrite_missing_audio_and_other_user(self):
        self.seed()
        with self.assertRaises(HTTPException):
            prepare_retry(self.db, "l", "other")
        self.db.add(TranscriptSegment(lesson_id="l", speaker="说话人", start_ms=0, end_ms=100, text="保留文字"))
        self.db.commit()
        with self.assertRaises(HTTPException):
            prepare_retry(self.db, "l", "owner")
        self.assertEqual(self.db.scalar(select(TranscriptSegment)).text, "保留文字")
        self.db.add(Lesson(id="noaudio", course_id="c", title="没有录音", status="failed"))
        self.db.flush()
        self.db.add(ProcessingJob(lesson_id="noaudio", stage="failed"))
        self.db.commit()
        with self.assertRaises(HTTPException):
            prepare_retry(self.db, "noaudio", "owner")

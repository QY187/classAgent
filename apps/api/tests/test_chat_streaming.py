import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from fastapi import HTTPException
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.modules.chat.streaming import message_events, encode_event
from app.modules.chat.sending import send_message
from app.modules.chat.conversations import create_conversation
from app.modules.chat.messages import read_messages


class ChatStreamTransportTest(unittest.TestCase):
    def test_saved_history_datetime_is_encoded_like_normal_api_response(self):
        event = encode_event("done", {"created_at": datetime(2026, 10, 2, tzinfo=timezone.utc)})
        self.assertEqual(json.loads(event.split("data: ")[1]), {"created_at": "2026-10-02T00:00:00+00:00"})

    @patch("app.modules.chat.streaming.SessionLocal")
    @patch("app.modules.chat.streaming.send_message")
    def test_preview_then_saved_history_and_done(self, send, sessions):
        def generate(*args, **kwargs):
            kwargs["on_progress"]({"answer": "第一条 [1]", "citations": [{"id": 1}]})
            return {"messages": [{"content": "第一条 [1]"}]}
        send.side_effect = generate
        async def collect():
            return [event async for event in message_events("c", "owner", "问题", "r")]
        events = asyncio.run(collect())
        self.assertEqual([event.splitlines()[0] for event in events], ["event: status", "event: answer", "event: done"])
        self.assertIn("第一条", events[1])

    @patch("app.modules.chat.streaming.SessionLocal")
    @patch("app.modules.chat.streaming.send_message", side_effect=HTTPException(409, "正在回答"))
    def test_failure_event_has_no_done(self, send, sessions):
        async def collect():
            return [event async for event in message_events("c", "owner", "问题", "r")]
        events = asyncio.run(collect())
        self.assertEqual(events[-1], 'event: error\ndata: {"detail": "正在回答"}\n\n')


class ChatStreamPersistenceTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.chat.sending.ask_course")
    def test_preview_is_not_saved_as_completed_until_generation_finishes(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            preview = Mock()
            def generate(*args, **kwargs):
                kwargs["on_progress"]({"answer": "临时结论", "citations": []})
                rows = read_messages(db, chat["id"], "owner")["messages"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "pending")
                return {"answer": "完整回答", "citations": []}
            ask.side_effect = generate
            result = send_message(db, chat["id"], "owner", "课堂问题", "r", on_progress=preview)
            preview.assert_called_once()
            self.assertEqual(result["messages"][-1]["content"], "完整回答")
            self.assertFalse(result["conversation"]["generating"])
            # 重连同一请求只返回已保存历史，不重复生成。
            send_message(db, chat["id"], "owner", "课堂问题", "r", on_progress=preview)
            self.assertEqual(ask.call_count, 1)

    @patch("app.modules.chat.sending.ask_course")
    def test_failed_stream_keeps_question_retryable(self, ask):
        with Session(self.engine) as db:
            chat = create_conversation(db, "l", "owner")
            def generate(*args, **kwargs):
                kwargs["on_progress"]({"answer": "临时结论", "citations": []})
                raise HTTPException(502, "模型流中断")
            ask.side_effect = generate
            with self.assertRaises(HTTPException):
                send_message(db, chat["id"], "owner", "课堂问题", "r", on_progress=Mock())
            history = read_messages(db, chat["id"], "owner")
            self.assertEqual(len(history["messages"]), 1)
            self.assertEqual(history["messages"][0]["status"], "failed")
            self.assertFalse(history["conversation"]["generating"])

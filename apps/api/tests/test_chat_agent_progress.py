import asyncio
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.chat.streaming import message_events
from app.modules.chat.cancellation import stop_generation
from app.modules.chat.generation import GenerationStopped


class AgentProgressTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.chat.sending.run_agent")
    def test_progress_is_saved_and_failed_tool_can_be_followed_by_success(self, agent):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            events = []
            def generate(*args, **kwargs):
                emit = kwargs["on_step"]
                emit({"id": "a", "tool": "get_transcript", "status": "running", "arguments": "secret"})
                emit({"id": "a", "tool": "get_transcript", "status": "failed", "error_code": "not_found"})
                emit({"id": "b", "tool": "list_courses", "status": "completed"})
                return {"answer": "课程目录", "citations": []}
            agent.side_effect = generate
            result = send_message(db, chat["id"], "owner", "查询课程", "r", on_step=events.append)
            steps = result["messages"][0]["steps"]
            self.assertEqual([item["status"] for item in steps], ["failed", "completed"])
            self.assertEqual(len(events), 3)
            self.assertNotIn("secret", str(steps))
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["steps"], steps)
            send_message(db, chat["id"], "owner", "查询课程", "r", on_step=events.append)
            agent.assert_called_once()

    @patch("app.modules.chat.sending.run_agent")
    def test_failure_retry_replaces_previous_steps(self, agent):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            def fail(*args, **kwargs):
                kwargs["on_step"]({"id": "old", "tool": "list_courses", "status": "running"})
                raise HTTPException(502, "模型不可用")
            agent.side_effect = fail
            with self.assertRaises(HTTPException):
                send_message(db, chat["id"], "owner", "查询课程", "r")
            self.assertEqual(len(read_messages(db, chat["id"], "owner")["messages"][0]["steps"]), 1)
            agent.side_effect = lambda *args, **kwargs: {"answer": "无资料", "citations": []}
            result = send_message(db, chat["id"], "owner", "查询课程", "r")
            self.assertEqual(result["messages"][0]["steps"], [])

    @patch("app.modules.chat.sending.run_agent")
    def test_stopped_run_cannot_publish_later_steps(self, agent):
        with Session(self.engine) as db:
            chat = create_global_conversation(db, "owner")
            events = []
            def generate(*args, **kwargs):
                emit = kwargs["on_step"]
                emit({"id": "a", "tool": "list_courses", "status": "running"})
                stop_generation(db, chat["id"], "owner", "r")
                with self.assertRaises(GenerationStopped):
                    emit({"id": "a", "tool": "list_courses", "status": "completed"})
                raise GenerationStopped()
            agent.side_effect = generate
            result = send_message(db, chat["id"], "owner", "查询课程", "r", on_step=events.append)
            self.assertEqual(len(events), 1)
            self.assertEqual(result["messages"][0]["status"], "cancelled")

    @patch("app.modules.chat.streaming.SessionLocal")
    @patch("app.modules.chat.streaming.send_message")
    def test_step_events_precede_done(self, send, sessions):
        def generate(*args, **kwargs):
            kwargs["on_step"]({"request_id": "r", "steps": [{"id": "a", "label": "查询课程", "status": "running"}]})
            kwargs["on_step"]({"request_id": "r", "steps": [{"id": "a", "label": "查询课程", "status": "completed"}]})
            return {"messages": []}
        send.side_effect = generate
        async def collect():
            return [event async for event in message_events("c", "owner", "问题", "r")]
        events = asyncio.run(collect())
        self.assertEqual([event.splitlines()[0] for event in events], ["event: status", "event: step", "event: step", "event: done"])

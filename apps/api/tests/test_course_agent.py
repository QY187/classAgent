import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import Course, Lesson, TranscriptSegment, User, ChatMessage, now_utc
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.chat.cancellation import stop_generation


def call(name, args, identity):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}


def answer():
    return {"role": "assistant", "content": json.dumps({"claims": [{"text": "课堂内容", "source_ids": ["E1"]}]})}


class CourseAgentTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def seed_other_courses(self, db):
        db.add(User(id="other", username="other", password_hash="x")); db.flush()
        db.add_all([Course(id="c2", owner_id="u", name="数学"), Course(id="foreign", owner_id="other", name="私有课程")]); db.flush()
        db.add_all([Lesson(id="l2", course_id="c2", title="数学课"), Lesson(id="private", course_id="foreign", title="私有课次")]); db.flush()
        db.add_all([TranscriptSegment(id="s2", lesson_id="l2", start_ms=10, end_ms=20, text="其他课程秘密"),
                    TranscriptSegment(id="secret", lesson_id="private", start_ms=30, end_ms=40, text="其他用户秘密")]); db.commit()

    @patch("app.modules.agent.loop.complete")
    def test_existing_course_conversation_preserves_history_citations_and_steps(self, model):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            db.add_all([ChatMessage(conversation_id=chat["id"], request_id="old", position=1, role="user", content="之前的问题"),
                        ChatMessage(conversation_id=chat["id"], request_id="old", position=2, role="assistant", content="以前的回答")]); db.commit()
            model.side_effect = [call("list_lessons", {"course_id": "c"}, "list"), call("get_transcript", {"lesson_id": "l"}, "read"), answer()]
            events = []
            result = send_message(db, chat["id"], "owner", "这门课程讲了什么", "r", on_step=events.append)
            question, reply = result["messages"][-2:]
            self.assertEqual(result["conversation"]["scope"], "course")
            self.assertEqual([step["status"] for step in question["steps"]], ["completed", "completed"])
            self.assertEqual(len(events), 4)
            self.assertEqual(reply["citations"][0]["segment_ids"], ["s"])
            self.assertEqual(reply["citations"][0]["lesson_id"], "l")
            self.assertEqual(reply["citations"][0]["start_ms"], 0)
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)
            prompts = model.call_args.args[0]
            self.assertIn('"course_id": "c"', prompts[0]["content"])
            self.assertEqual([item["content"] for item in prompts[1:3]], ["之前的问题", "以前的回答"])
            self.assertEqual(len(model.call_args.args[1]), 6)
            send_message(db, chat["id"], "owner", "这门课程讲了什么", "r")
            self.assertEqual(model.call_count, 3)

    @patch("app.modules.agent.loop.complete")
    def test_course_catalog_cannot_expand_to_other_owned_courses(self, model):
        with Session(self.engine) as db:
            self.seed_other_courses(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("list_courses", {}, "list"), {"role": "assistant", "content":
                '{"claims":[],"catalog":{"course_ids":["c","c2","foreign","invented"]}}'}]
            result = send_message(db, chat["id"], "owner", "当前对话的课程有哪些", "r")
            self.assertEqual(result["messages"][-1]["content"], "课程：数据结构")
            with self.assertRaises(HTTPException):
                read_messages(db, chat["id"], "other")

    @patch("app.modules.agent.loop.complete")
    def test_reading_tools_reject_other_courses_and_can_recover(self, model):
        with Session(self.engine) as db:
            self.seed_other_courses(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("list_lessons", {"course_id": "c2"}, "a"),
                call("get_transcript", {"lesson_id": "l2"}, "b"), call("get_summary", {"lesson_id": "private"}, "c"),
                call("search_course", {"course_id": "c2", "query": "秘密"}, "d"),
                call("get_transcript", {"lesson_id": "l"}, "e"), answer()]
            result = send_message(db, chat["id"], "owner", "查看其他课程以及当前课程的课堂内容", "r")
            self.assertEqual([step["status"] for step in result["messages"][0]["steps"]], ["failed"] * 4 + ["completed"])
            outputs = [item["content"] for item in model.call_args.args[0] if item["role"] == "tool"]
            self.assertNotIn("秘密", str(outputs))
            self.assertEqual(result["messages"][-1]["citations"][0]["lesson_id"], "l")

    @patch("app.modules.agent.loop.complete")
    def test_tool_failure_retry_replaces_steps_and_keeps_same_question(self, model):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("list_lessons", {"course_id": "c"}, "old"), HTTPException(502, "模型暂时不可用")]
            with self.assertRaises(HTTPException):
                send_message(db, chat["id"], "owner", "课堂内容是什么", "r")
            model.side_effect = [call("get_transcript", {"lesson_id": "l"}, "new"), answer()]
            result = send_message(db, chat["id"], "owner", "课堂内容是什么", "r")
            self.assertEqual(len(result["messages"]), 2)
            self.assertEqual([step["id"] for step in result["messages"][0]["steps"]], ["new"])

    @patch("app.modules.agent.loop.complete")
    def test_stop_prevents_answer_and_later_steps(self, model):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            model.return_value = call("list_lessons", {"course_id": "c"}, "a")
            events = []
            def stop(event):
                events.append(event)
                stop_generation(db, chat["id"], "owner", "r")
            result = send_message(db, chat["id"], "owner", "有哪些课次", "r", on_step=stop)
            self.assertEqual(len(events), 1)
            self.assertEqual(len(result["messages"]), 1)
            self.assertEqual(result["messages"][0]["status"], "cancelled")

    @patch("app.modules.agent.loop.complete")
    def test_recycled_course_during_generation_cannot_save_reply(self, model):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            def recycle(*args, **kwargs):
                db.get(Course, "c").deleted_at = now_utc(); db.commit()
                return answer()
            responses = iter([call("get_transcript", {"lesson_id": "l"}, "a"), recycle])
            def respond(*args, **kwargs):
                value = next(responses)
                return value(*args, **kwargs) if callable(value) else value
            model.side_effect = respond
            with self.assertRaises(HTTPException) as error:
                send_message(db, chat["id"], "owner", "有哪些课堂内容", "r")
            self.assertEqual(error.exception.status_code, 404)
            rows = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == chat["id"])
                                   .execution_options(include_deleted=True)))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "failed")

import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from test_agent_quiz import call
from app.shared.models import Course, Lesson, TranscriptSegment, Quiz, ChatMessage, ChatConversation, now_utc
from app.modules.agent.schemas import QuizArguments
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.chat.quiz_actions import generate_for_message
from app.modules.chat.cancellation import stop_generation


class CourseQuizTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def seed(self, db):
        db.add_all([TranscriptSegment(id="s2", lesson_id="l", start_ms=2, end_ms=3, text="第二段原文依据"),
                    TranscriptSegment(id="s3", lesson_id="l", start_ms=3, end_ms=4, text="第三段原文依据")]); db.commit()

    def generated(self, segments, count, question_type):
        questions = []
        for index in range(count):
            kind = question_type if question_type != "mixed" else ("single_choice" if index % 2 else "true_false")
            source = segments[index % len(segments)]
            questions.append({"kind": kind, "stem": f"题目{index}", "options": ["正确", "错误"] if kind == "true_false" else ["A", "B", "C", "D"],
                "correct_option": 0, "explanation": "提交后查看的解析", "source": source, "evidence": source.text})
        return questions

    def responses(self, lesson_ids=None, question_type="true_false"):
        args = {"course_id": "c", "count": 3, "question_type": question_type}
        if lesson_ids:
            args["lesson_ids"] = lesson_ids
        return [call("list_courses", {}, "a"), call("list_lessons", {"course_id": "c"}, "b"), call("generate_quiz", args, "q")]

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_default_course_result_card_types_and_retry(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db); generator.side_effect = self.generated
            chat = create_course_conversation(db, "c", "owner")
            # 当前课程已由对话绑定；模型可以先查询课次，无需重复查询课程目录。
            model.side_effect = self.responses()[1:]
            result = send_message(db, chat["id"], "owner", "给我生成3道判断题", "r")
            artifact = result["messages"][0]["artifacts"][0]
            self.assertEqual(artifact["course_id"], "c")
            self.assertEqual(artifact["lesson_ids"], [])
            self.assertEqual(artifact["question_count"], 3)
            quiz = db.get(Quiz, artifact["id"])
            self.assertTrue(all(question.kind == "true_false" for question in quiz.questions))
            self.assertEqual(quiz.status, "ready")
            self.assertNotIn("correct_option", str(result))
            self.assertNotIn("提交后查看的解析", str(result))
            self.assertEqual(result["messages"][0]["steps"][-1]["label"], "生成课堂小测")
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)
            self.assertEqual(send_message(db, chat["id"], "owner", "给我生成3道判断题", "r"), result)
            generator.assert_called_once()
            self.assertEqual(model.call_count, 2)
            db.get(Course, "c").deleted_at = now_utc(); db.commit()
            with self.assertRaises(HTTPException):
                read_messages(db, chat["id"], "owner")
            db.get(Course, "c", execution_options={"include_deleted": True}).deleted_at = None; db.commit()
            self.assertEqual(read_messages(db, chat["id"], "owner")["messages"][0]["artifacts"], [artifact])

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_selected_lesson_and_short_scope_clarification(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db); generator.side_effect = self.generated
            chat = create_course_conversation(db, "c", "owner")
            model.return_value = {"role": "assistant", "content": '{"claims":[],"outcome":"needs_input","question":"你想根据哪一节课生成？"}'}
            send_message(db, chat["id"], "owner", "生成3道单选题", "first")
            generator.assert_not_called()
            model.side_effect = self.responses(["l"], "single_choice")
            result = send_message(db, chat["id"], "owner", "二叉树这节课", "follow")
            artifact = result["messages"][-2]["artifacts"][0]
            self.assertEqual(artifact["lesson_ids"], ["l"])
            self.assertTrue(all(question.kind == "single_choice" and question.source_lesson_id == "l"
                                for question in db.get(Quiz, artifact["id"]).questions))

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_other_owned_course_and_lesson_cannot_generate(self, model, generator):
        with Session(self.engine) as db:
            db.add(Course(id="c2", owner_id="u", name="数学")); db.flush()
            db.add(Lesson(id="l2", course_id="c2", title="数学第一讲")); db.commit()
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = [call("generate_quiz", {"course_id": "c2", "count": 3}, "outside"),
                call("list_courses", {}, "a"), call("list_lessons", {"course_id": "c"}, "b"),
                call("generate_quiz", {"course_id": "c", "lesson_ids": ["l2"], "count": 3}, "lesson"),
                {"role": "assistant", "content": '{"claims":[],"outcome":"needs_input","question":"请在当前课程选择课次，或进入其他课程对话。"}'}]
            result = send_message(db, chat["id"], "owner", "请生成3道小测题", "r")
            self.assertEqual(result["messages"][0]["steps"][0]["status"], "failed")
            self.assertEqual(result["messages"][0]["artifacts"], [])
            generator.assert_not_called()

    @patch("app.modules.quizzes.service._generate_questions")
    def test_action_callback_rechecks_course_binding(self, generator):
        with Session(self.engine) as db:
            db.add(Course(id="c2", owner_id="u", name="数学")); db.commit()
            chat = create_course_conversation(db, "c", "owner")
            conversation = db.get(ChatConversation, chat["id"])
            conversation.generation_token = "token"
            db.add(ChatMessage(id="request", conversation_id=chat["id"], request_id="r", position=1,
                               role="user", content="生成小测", status="pending")); db.commit()
            with self.assertRaises(HTTPException) as forbidden:
                generate_for_message(db, chat["id"], "owner", "request", "token", QuizArguments(course_id="c2"))
            self.assertEqual(forbidden.exception.status_code, 404)
            generator.assert_not_called()

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_stop_during_generation_cannot_save_quiz(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses(["l"])
            def stop(*args):
                questions = self.generated(*args)
                stop_generation(db, chat["id"], "owner", "r")
                return questions
            generator.side_effect = stop
            result = send_message(db, chat["id"], "owner", "生成3道判断题", "r")
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_recycled_source_before_save_cannot_create_quiz(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses(["l"])
            def recycle(*args):
                questions = self.generated(*args)
                db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
                return questions
            generator.side_effect = recycle
            result = send_message(db, chat["id"], "owner", "生成3道判断题", "r")
            self.assertEqual(result["messages"][0]["artifacts"], [])
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])
            self.assertEqual(result["messages"][0]["steps"][-1]["status"], "failed")
            self.assertEqual(result["messages"][0]["steps"][-1]["error"], "小测生成失败，请查看回答说明")

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_source_moved_to_another_course_before_save_cannot_create_quiz(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db)
            db.add(Course(id="c2", owner_id="u", name="数学")); db.commit()
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            def move(*args):
                questions = self.generated(*args)
                db.get(Lesson, "l").course_id = "c2"; db.commit()
                return questions
            generator.side_effect = move
            result = send_message(db, chat["id"], "owner", "生成3道判断题", "r")
            self.assertEqual(result["messages"][0]["artifacts"], [])
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])
            self.assertIn("出题范围已变更", result["messages"][-1]["content"])

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_new_request_cannot_reuse_old_success_text_and_can_retry_independently(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db); generator.side_effect = self.generated
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses(["l"])
            first = send_message(db, chat["id"], "owner", "根据二叉树这节课生成3道判断题", "first")
            first_quiz = first["messages"][0]["artifacts"][0]["id"]
            model.side_effect = None
            model.return_value = {"role": "assistant", "content": first["messages"][-1]["content"]}
            with self.assertRaises(HTTPException):
                send_message(db, chat["id"], "owner", "生成3道判断题", "next")
            latest = read_messages(db, chat["id"], "owner")["messages"][-1]
            self.assertEqual(latest["status"], "failed")
            self.assertEqual(latest["artifacts"], [])
            self.assertTrue(any("不能代替本次执行" in item.get("content", "")
                for item in model.call_args.args[0] if item["role"] == "system"))
            model.side_effect = self.responses()[1:]
            second = send_message(db, chat["id"], "owner", "生成3道判断题", "next")
            second_quiz = second["messages"][-2]["artifacts"][0]
            self.assertNotEqual(second_quiz["id"], first_quiz)
            self.assertEqual(second_quiz["lesson_ids"], [])
            self.assertEqual(len(second["messages"]), 4)
            self.assertEqual(generator.call_count, 2)
            self.assertEqual(len(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None))))), 2)

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_plain_and_negative_requests_never_enable_quiz_tool(self, model, generator):
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            model.return_value = {"role": "assistant", "content": '{"claims":[],"outcome":"insufficient_evidence"}'}
            for index, question in enumerate(["有哪些知识点", "不要生成小测", "如何生成小测"]):
                send_message(db, chat["id"], "owner", question, f"r{index}")
                names = [schema["function"]["name"] for schema in model.call_args.args[1]]
                self.assertNotIn("generate_quiz", names)
            generator.assert_not_called()

import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from test_course_agent import call
from app.shared.models import Course, Lesson, Quiz, ReviewCard, TranscriptSegment, now_utc
from app.modules.agent.schemas import PracticeQuizArguments
from app.modules.agent.executor import execute_tool
from app.modules.agent.tools import ToolContext
from app.modules.agent.registry import tool_schemas
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message
from app.modules.chat.messages import read_messages
from app.modules.chat.cancellation import stop_generation
from app.modules.chat.quiz_actions import wants_practice_quiz
from app.modules.quizzes.schemas import QuizGenerate, QuizSubmit
from app.modules.quizzes.service import generate_quiz, submit_quiz
from app.modules.quizzes.practice import PracticeSelection


class AgentPracticeTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    def seed(self, db):
        source = db.get(TranscriptSegment, "s")
        source.text = "非空二叉树中，叶子节点数等于度为二的节点数加一。"
        card = db.get(ReviewCard, "r")
        card.title = "叶子节点与度为二的节点数量关系"
        card.body = "叶子节点数等于度为二的节点数加一。"
        card.status = "review"
        card.source_segment_id = "s"
        card.source_excerpt = source.text
        question = db.get(Quiz, "q").questions[0]
        question.stem = "叶子节点数一定等于度为二的节点数吗？"
        question.source_segment_id = "s"
        question.source_lesson_id = "l"
        question.source_excerpt = source.text
        # 同一课次中的无关来源不应被混入练习。
        db.add_all([TranscriptSegment(id=f"other-{i}", lesson_id="l", start_ms=i+10, end_ms=i+11, text="无关课堂内容") for i in range(3)])
        db.commit()

    def generated(self, segments, count, kind, **kwargs):
        self.assertEqual([source.id for source in segments], ["s"])
        self.assertTrue(kwargs["focus_topics"])
        self.assertIn("叶子节点", str(kwargs["focus_topics"]))
        self.assertIn("叶子节点", kwargs["source_windows"]["s"])
        return [{"kind": "true_false", "stem": f"新练习题 {i}", "options": ["正确", "错误"], "correct_option": 0,
                 "explanation": "答题后才能查看的解析", "source": segments[0], "evidence": "叶子节点数等于度为二的节点数加一"} for i in range(count)]

    def responses(self, wrong=False):
        return [call("list_wrong_questions" if wrong else "list_knowledge_points", {"status": "pending" if wrong else "review"}, "read"),
                call("generate_practice_quiz", {"course_id": "c", "wrong_question_ids" if wrong else "knowledge_point_ids": ["question" if wrong else "r"], "count": 3, "question_type": "true_false"}, "generate")]

    def test_intent_and_capability_isolation(self):
        self.assertTrue(wants_practice_quiz("根据错题给我出3道判断题"))
        self.assertTrue(wants_practice_quiz("根据需要复习的知识点生成小测"))
        clarification = [{"role": "user", "content": "根据薄弱点生成3道题"}, {"role": "assistant", "content": "哪门课程？"}]
        self.assertTrue(wants_practice_quiz("数据结构课程", clarification))
        for text in ("错题有哪些", "不要根据错题生成小测", "怎么根据错题出题", "生成3道判断题"):
            self.assertFalse(wants_practice_quiz(text, clarification))
        with self.assertRaises(ValueError):
            PracticeQuizArguments(course_id="c")
        names = [row["function"]["name"] for row in tool_schemas(include_actions=True, practice_only=True)]
        self.assertIn("generate_practice_quiz", names)
        self.assertNotIn("generate_quiz", names)
        with Session(self.engine) as db:
            self.assertFalse(execute_tool(db, ToolContext("owner"), "generate_practice_quiz", {"course_id": "c", "knowledge_point_ids": ["r"]})["ok"])

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_course_chat_generates_new_targeted_quiz_without_answers_and_is_idempotent(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db); generator.side_effect = self.generated
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            result = send_message(db, chat["id"], "owner", "根据需要复习的知识点生成3道判断题", "r")
            question, reply = result["messages"]
            self.assertEqual([step["label"] for step in question["steps"]], ["查询知识点状态", "生成薄弱点练习"])
            artifact = question["artifacts"][0]
            self.assertIn("薄弱点练习", artifact["title"])
            self.assertEqual(artifact["lesson_ids"], ["l"])
            self.assertEqual({q.source_segment_id for q in db.get(Quiz, artifact["id"]).questions}, {"s"})
            self.assertNotIn("correct_option", str(result)); self.assertNotIn("答题后才能查看", str(result))
            self.assertIn("3 道薄弱点练习题", reply["content"])
            self.assertEqual(db.get(ReviewCard, "r").status, "review")
            self.assertEqual(read_messages(db, chat["id"], "owner"), result)
            self.assertEqual(send_message(db, chat["id"], "owner", "根据需要复习的知识点生成3道判断题", "r"), result)
            generator.assert_called_once()

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_wrong_question_sources_create_new_quiz_and_keep_attempt_records(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db); submit_quiz(db, "q", QuizSubmit(answers={"question": 1}), "owner")
            generator.side_effect = self.generated
            model.side_effect = self.responses(wrong=True)
            chat = create_course_conversation(db, "c", "owner")
            result = send_message(db, chat["id"], "owner", "根据错题生成3道判断题", "r")
            self.assertNotEqual(result["messages"][0]["artifacts"][0]["id"], "q")
            row = execute_tool(db, ToolContext("owner", "c"), "list_wrong_questions", {})["data"]["items"][0]
            self.assertEqual((row["status"], row["wrong_count"], row["retry_count"]), ("pending", 1, 0))

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_unqueried_targets_are_rejected(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()[1:]
            result = send_message(db, chat["id"], "owner", "根据薄弱点生成3道题", "r")
            self.assertIn("先查询", result["messages"][-1]["content"])
            self.assertEqual(result["messages"][0]["artifacts"], [])
            generator.assert_not_called()

    @patch("app.modules.quizzes.service._generate_questions")
    def test_mastered_new_missing_source_and_stale_source_cannot_fall_back_to_general(self, generator):
        with Session(self.engine) as db:
            self.seed(db)
            card = db.get(ReviewCard, "r")
            for status in ("mastered", "new"):
                card.status = status; db.commit()
                with self.assertRaises(HTTPException):
                    generate_quiz(db, "c", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))
            card.status = "review"; card.source_segment_id = None; db.commit()
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))
            card.source_segment_id = "s"; card.source_excerpt = "过期原文"; db.commit()
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))
            generator.assert_not_called()

    @patch("app.modules.quizzes.service._generate_questions")
    def test_targets_and_sources_cannot_cross_course(self, generator):
        with Session(self.engine) as db:
            self.seed(db)
            db.add(Course(id="c2", owner_id="u", name="数学")); db.flush()
            db.add(Lesson(id="l2", course_id="c2", title="数学课")); db.commit()
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c2", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))
            db.get(TranscriptSegment, "s").lesson_id = "l2"; db.commit()
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))
            generator.assert_not_called()

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_status_changed_during_generation_prevents_save(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            def changed(*args, **kwargs):
                result = self.generated(*args, **kwargs)
                db.get(ReviewCard, "r").status = "mastered"; db.commit()
                return result
            generator.side_effect = changed
            result = send_message(db, chat["id"], "owner", "根据需要复习的知识点生成3道题", "r")
            self.assertEqual(result["messages"][0]["artifacts"], [])
            self.assertIn("重新查询", result["messages"][-1]["content"])
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])

    @patch("app.modules.quizzes.service._generate_questions")
    @patch("app.modules.agent.loop.complete")
    def test_stopping_generation_prevents_new_quiz(self, model, generator):
        with Session(self.engine) as db:
            self.seed(db)
            chat = create_course_conversation(db, "c", "owner")
            model.side_effect = self.responses()
            def stopped(*args, **kwargs):
                result = self.generated(*args, **kwargs)
                stop_generation(db, chat["id"], "owner", "r")
                return result
            generator.side_effect = stopped
            result = send_message(db, chat["id"], "owner", "根据薄弱点生成3道题", "r")
            self.assertEqual(result["messages"][0]["status"], "cancelled")
            self.assertEqual(list(db.scalars(select(Quiz).where(Quiz.agent_request_key.is_not(None)))), [])

    @patch("app.modules.quizzes.service._generate_questions")
    def test_recycled_source_or_unrelated_generated_source_prevents_save(self, generator):
        with Session(self.engine) as db:
            self.seed(db)
            def recycled(*args, **kwargs):
                result = self.generated(*args, **kwargs)
                db.get(Lesson, "l").deleted_at = now_utc(); db.commit()
                return result
            generator.side_effect = recycled
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))
            db.get(Lesson, "l", execution_options={"include_deleted": True}).deleted_at = None; db.commit()
            def unrelated(*args, **kwargs):
                result = self.generated(*args, **kwargs)
                result[0]["source"] = db.get(TranscriptSegment, "other-0")
                return result
            generator.side_effect = unrelated
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c", QuizGenerate(count=3), "owner", practice=PracticeSelection(("r",)))

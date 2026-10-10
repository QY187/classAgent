import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.quizzes.service import _generate_questions, _source_segments, add_wrong_answer_to_review, generate_quiz, get_attempt, get_quiz, list_attempts, list_quizzes, list_wrong_questions, publish_quiz, retry_wrong_question, submit_quiz, update_question
from app.modules.quizzes.migrations import prepare_quiz_scope
from app.modules.quizzes.schemas import QuizGenerate, QuizQuestionUpdate, QuizSubmit, WrongQuestionRetry
from app.shared.models import Course, Lesson, Quiz, QuizQuestionRetry, ReviewCard, TranscriptSegment, User


class QuizTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add_all([User(id="u1", username="owner", password_hash="x"), User(id="u2", username="other", password_hash="x")])
            db.flush()
            db.add(Course(id="c1", owner_id="u1", name="数据结构"))
            db.flush()
            db.add(Lesson(id="l1", course_id="c1", title="二叉树"))
            db.flush()
            db.add_all([TranscriptSegment(id=f"s{i}", lesson_id="l1", speaker="老师", start_ms=i * 1000,
                                          end_ms=i * 1000 + 900, text=f"第{i}层最多有两个的{i-1}次方个节点。") for i in range(1, 5)])
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def ready_quiz(self, db):
        source = db.get(TranscriptSegment, "s1")
        generated = [{"kind": "true_false", "stem": f"判断题 {i}", "options": ["正确", "错误"],
                      "correct_option": 0, "explanation": "依据原文", "source": source, "evidence": source.text[:8]} for i in range(3)]
        with patch("app.modules.quizzes.service._generate_questions", return_value=generated):
            draft = generate_quiz(db, "c1", QuizGenerate(lesson_id="l1"), "owner")
        return publish_quiz(db, draft["id"], "owner")

    def test_generation_supports_fifteen_questions_and_rejects_out_of_range_counts(self):
        with Session(self.engine) as db:
            source = db.get(TranscriptSegment, "s1")
            generated = [{"kind": "true_false", "stem": f"判断题 {i}", "options": ["正确", "错误"],
                          "correct_option": 0, "explanation": "依据原文", "source": source, "evidence": source.text[:8]} for i in range(15)]
            with patch("app.modules.quizzes.service._generate_questions", return_value=generated) as generator:
                quiz = generate_quiz(db, "c1", QuizGenerate(count=15), "owner")
            self.assertEqual(generator.call_args.args[1], 15)
            self.assertEqual(len(quiz["questions"]), 15)
            self.assertEqual(QuizGenerate().count, 5)
            for count in (2, 16):
                with self.assertRaises(ValidationError):
                    QuizGenerate(count=count)

    def test_selected_lessons_limit_sources_and_preserve_history_scope(self):
        with Session(self.engine) as db:
            db.add_all([Lesson(id="l2", course_id="c1", title="第二讲"), Lesson(id="l3", course_id="c1", title="未选择的第三讲"),
                        Lesson(id="empty", course_id="c1", title="无文字记录")])
            db.add(Course(id="c2", owner_id="u2", name="其他用户课程"))
            db.flush()
            db.add(Lesson(id="foreign", course_id="c2", title="其他用户课次"))
            db.add_all([TranscriptSegment(id=f"{lesson}-{i}", lesson_id=lesson, speaker="老师", start_ms=i * 1000,
                                           end_ms=i * 1000 + 900, text=f"{lesson} 的课堂记录第{i}段。") for lesson in ("l2", "l3") for i in range(3)])
            db.commit()
            def generated(segments, count, question_type):
                self.assertEqual({segment.lesson_id for segment in segments}, {"l1", "l2"})
                self.assertEqual((count, question_type), (10, "single_choice"))
                return [{"kind": "single_choice", "stem": f"题目 {i}", "options": ["一", "二", "三", "四"],
                         "correct_option": 0, "explanation": "原文依据", "source": source, "evidence": source.text[:8]} for i, source in enumerate(segments[:3])]
            with patch("app.modules.quizzes.service._generate_questions", side_effect=generated):
                quiz = generate_quiz(db, "c1", QuizGenerate(lesson_ids=["l1", "l2", "l1"], count=10, question_type="single_choice"), "owner")
            self.assertIsNone(quiz["lesson_id"])
            self.assertEqual(quiz["lesson_ids"], ["l1", "l2"])
            self.assertEqual(get_quiz(db, quiz["id"], "owner")["lesson_ids"], ["l1", "l2"])
            self.assertEqual(list_quizzes(db, "c1", "owner")[0]["lesson_ids"], ["l1", "l2"])
            for ids in (["foreign"], ["missing"], ["l1", "empty"]):
                with patch("app.modules.quizzes.service._generate_questions") as generator:
                    with self.assertRaises(HTTPException) as invalid:
                        generate_quiz(db, "c1", QuizGenerate(lesson_ids=ids), "owner")
                    self.assertEqual(invalid.exception.status_code, 400)
                    generator.assert_not_called()
            db.get(Lesson, "l3").deleted_at = datetime.now(timezone.utc)
            db.commit()
            with self.assertRaises(HTTPException):
                generate_quiz(db, "c1", QuizGenerate(lesson_ids=["l3"]), "owner")
            legacy = Quiz(course_id="c1", lesson_id="l1", title="存量单课次小测")
            db.add(legacy); db.commit()
            self.assertEqual(get_quiz(db, legacy.id, "owner")["lesson_ids"], ["l1"])
            for payload in ({"lesson_ids": []}, {"lesson_id": "l1", "lesson_ids": ["l2"]}, {"lesson_ids": [""]}):
                with self.assertRaises(ValidationError):
                    QuizGenerate(**payload)

    def test_source_sampling_keeps_short_selected_lesson(self):
        with Session(self.engine) as db:
            db.add(Lesson(id="short", course_id="c1", title="短课次")); db.flush()
            db.add(TranscriptSegment(id="short-source", lesson_id="short", speaker="老师", start_ms=0, end_ms=1000, text="短课次的有效记录。"))
            db.add_all([TranscriptSegment(id=f"long-{i}", lesson_id="l1", speaker="老师", start_ms=i * 1000,
                                          end_ms=i * 1000 + 900, text="长课次有效记录。") for i in range(100)])
            db.commit()
            segments = _source_segments(db, "c1", ["l1", "short"])
            self.assertEqual(len(segments), 60)
            self.assertEqual(len({segment.id for segment in segments}), 60)
            self.assertEqual({segment.lesson_id for segment in segments}, {"l1", "short"})

    def test_quiz_scope_migration_is_repeatable_and_keeps_old_rows(self):
        old_engine = create_engine("sqlite:///:memory:")
        try:
            with old_engine.begin() as connection:
                connection.execute(text("CREATE TABLE quizzes (id TEXT PRIMARY KEY, lesson_id TEXT)"))
                connection.execute(text("INSERT INTO quizzes VALUES ('old', 'l1')"))
            prepare_quiz_scope(old_engine); prepare_quiz_scope(old_engine)
            self.assertIn("lesson_ids_json", {column["name"] for column in inspect(old_engine).get_columns("quizzes")})
            with old_engine.connect() as connection:
                self.assertEqual(tuple(connection.execute(text("SELECT * FROM quizzes")).one()), ("old", "l1", None))
        finally:
            old_engine.dispose()

    def test_wrong_book_aggregates_history_and_isolates_users(self):
        with Session(self.engine) as db:
            quiz = self.ready_quiz(db)
            ids = [q["id"] for q in quiz["questions"]]
            submit_quiz(db, quiz["id"], QuizSubmit(answers=dict.fromkeys(ids, 1)), "owner")
            latest = submit_quiz(db, quiz["id"], QuizSubmit(answers={ids[0]: 1, ids[1]: 0, ids[2]: 0}), "owner")
            wrongs = list_wrong_questions(db, "owner", "c1")
            self.assertEqual(len(wrongs), 3)
            repeated = next(q for q in wrongs if q["id"] == ids[0])
            self.assertEqual(repeated["wrong_count"], 2)
            self.assertEqual(repeated["last_attempt_id"], latest["id"])
            self.assertNotIn("correct_option", repeated)
            self.assertEqual(list_wrong_questions(db, "other"), [])
            with self.assertRaises(HTTPException) as denied:
                list_wrong_questions(db, "other", "c1")
            self.assertEqual(denied.exception.status_code, 404)

    def test_retry_grades_independently_and_tracks_latest_result(self):
        with Session(self.engine) as db:
            quiz = self.ready_quiz(db)
            ids = [q["id"] for q in quiz["questions"]]
            original = submit_quiz(db, quiz["id"], QuizSubmit(answers={ids[0]: 1, ids[1]: 0, ids[2]: 0}), "owner")
            self.assertEqual(list_wrong_questions(db, "owner")[0]["status"], "pending")
            retry = retry_wrong_question(db, ids[0], WrongQuestionRetry(selected_option=0), "owner")
            self.assertTrue(retry["is_correct"])
            self.assertEqual(retry["correct_option"], 0)
            item = list_wrong_questions(db, "owner")[0]
            self.assertEqual((item["status"], item["wrong_count"], item["retry_count"]), ("mastered", 1, 1))
            self.assertEqual(get_attempt(db, original["id"], "owner")["correct_count"], 2)
            retry_wrong_question(db, ids[0], WrongQuestionRetry(selected_option=1), "owner")
            self.assertEqual(list_wrong_questions(db, "owner")[0]["status"], "pending")
            submit_quiz(db, quiz["id"], QuizSubmit(answers=dict.fromkeys(ids, 0)), "owner")
            self.assertEqual(list_wrong_questions(db, "owner")[0]["status"], "mastered")
            submit_quiz(db, quiz["id"], QuizSubmit(answers=dict.fromkeys(ids, 1)), "owner")
            self.assertEqual(list_wrong_questions(db, "owner")[0]["status"], "pending")
            db.execute(delete(Quiz).where(Quiz.id == quiz["id"]))
            db.commit()
            self.assertEqual(db.query(QuizQuestionRetry).count(), 0)

    def test_retry_rejects_other_users_non_wrong_questions_and_invalid_options(self):
        with Session(self.engine) as db:
            quiz = self.ready_quiz(db)
            ids = [q["id"] for q in quiz["questions"]]
            submit_quiz(db, quiz["id"], QuizSubmit(answers={ids[0]: 1, ids[1]: 0, ids[2]: 0}), "owner")
            for question_id, username, option, code in [(ids[0], "other", 0, 404), (ids[1], "owner", 0, 404),
                                                       (ids[0], "owner", 2, 400), ("missing", "owner", 0, 404)]:
                with self.assertRaises(HTTPException) as error:
                    retry_wrong_question(db, question_id, WrongQuestionRetry(selected_option=option), username)
                self.assertEqual(error.exception.status_code, code)
            self.assertEqual(db.query(QuizQuestionRetry).count(), 0)

    def test_generation_checks_evidence_and_drops_unsupported_question(self):
        with Session(self.engine) as db:
            segments = db.query(TranscriptSegment).order_by(TranscriptSegment.start_ms).all()
            payload = {"questions": [
                {"kind": "true_false", "stem": f"第{i}层有上限吗？", "options": ["正确", "错误"],
                 "correct_option": 0, "explanation": "课堂原话给出上限", "source_index": i,
                 "evidence": segments[i - 1].text[:8]} for i in range(1, 4)
            ] + [{"kind": "true_false", "stem": "无来源题", "options": ["正确", "错误"],
                  "correct_option": 0, "explanation": "猜测", "source_index": 4, "evidence": "课堂记录中不存在"}]}
            payload["questions"][0].update(kind="single_choice", options=["有上限", "没有上限", "取决于数值", "无法判断"])
            response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": __import__("json").dumps(payload)}}]})
            with patch("app.modules.quizzes.service.get_settings", return_value=SimpleNamespace(deepseek_api_key="test", summary_model="test")), \
                 patch("app.modules.quizzes.service.httpx.post", return_value=response):
                questions = _generate_questions(segments, 5)
            self.assertEqual(len(questions), 3)
            self.assertEqual(questions[0]["source"].id, "s1")

    def test_generation_enforces_selected_question_type(self):
        with Session(self.engine) as db:
            segments = db.query(TranscriptSegment).order_by(TranscriptSegment.start_ms).all()
            items = [{"kind": kind, "stem": f"{kind} 题目 {i}",
                      "options": ["正确", "错误"] if kind == "true_false" else ["选项一", "选项二", "选项三", "选项四"],
                      "correct_option": 0, "explanation": "原文依据", "source_index": 1,
                      "evidence": segments[0].text[:8]} for kind in ("true_false", "single_choice") for i in range(3)]
            response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices": [{"message": {"content": __import__("json").dumps({"questions": items})}}]})
            with patch("app.modules.quizzes.service.get_settings", return_value=SimpleNamespace(deepseek_api_key="test", summary_model="test")), \
                 patch("app.modules.quizzes.service.httpx.post", return_value=response):
                for kind in ("true_false", "single_choice"):
                    questions = _generate_questions(segments, 5, kind)
                    self.assertEqual(len(questions), 3)
                    self.assertEqual({q["kind"] for q in questions}, {kind})
                self.assertEqual({q["kind"] for q in _generate_questions(segments, 5, "mixed")}, {"true_false", "single_choice"})
                items[:] = items[:3]
                with self.assertRaises(HTTPException) as incomplete:
                    _generate_questions(segments, 5, "mixed")
                self.assertEqual(incomplete.exception.status_code, 502)
            with self.assertRaises(ValidationError):
                QuizGenerate(question_type="essay")

    def test_draft_can_be_reviewed_and_published_without_exposing_answers(self):
        with Session(self.engine) as db:
            source = db.get(TranscriptSegment, "s1")
            generated = [{"kind": "true_false", "stem": f"判断题 {i}", "options": ["正确", "错误"],
                          "correct_option": 0, "explanation": "依据原文", "source": source, "evidence": source.text[:8]} for i in range(3)]
            with patch("app.modules.quizzes.service._generate_questions", return_value=generated):
                draft = generate_quiz(db, "c1", QuizGenerate(lesson_id="l1"), "owner")
            self.assertEqual(draft["status"], "draft")
            self.assertEqual(len(draft["questions"]), 3)
            self.assertIn("correct_option", draft["questions"][0])
            quiz_id = draft["id"]
            with self.assertRaises(HTTPException) as denied:
                get_quiz(db, quiz_id, "other")
            self.assertEqual(denied.exception.status_code, 404)
            changed = update_question(db, quiz_id, draft["questions"][0]["id"],
                                      QuizQuestionUpdate(stem="修改后的题目", options=["正确", "错误"], correct_option=1,
                                                         explanation="修改后的解析"), "owner")
            self.assertEqual(changed["questions"][0]["correct_option"], 1)
            ready = publish_quiz(db, quiz_id, "owner")
            self.assertEqual(ready["status"], "ready")
            self.assertNotIn("correct_option", ready["questions"][0])
            with self.assertRaises(HTTPException) as locked:
                update_question(db, quiz_id, draft["questions"][0]["id"],
                                QuizQuestionUpdate(stem="再改", options=["正确", "错误"], correct_option=0,
                                                   explanation="解析"), "owner")
            self.assertEqual(locked.exception.status_code, 409)

            question_ids = [question["id"] for question in ready["questions"]]
            with self.assertRaises(HTTPException) as incomplete:
                submit_quiz(db, quiz_id, QuizSubmit(answers={question_ids[0]: 1}), "owner")
            self.assertEqual(incomplete.exception.status_code, 400)
            result = submit_quiz(db, quiz_id, QuizSubmit(answers={question_ids[0]: 1, question_ids[1]: 0, question_ids[2]: 1}), "owner")
            self.assertEqual((result["correct_count"], result["total_count"]), (2, 3))
            self.assertEqual([item["is_correct"] for item in result["questions"]], [True, True, False])
            self.assertEqual(len(list_attempts(db, quiz_id, "owner")), 1)
            self.assertEqual(get_attempt(db, result["id"], "owner")["questions"][0]["correct_option"], 1)
            with self.assertRaises(HTTPException) as private:
                get_attempt(db, result["id"], "other")
            self.assertEqual(private.exception.status_code, 404)

            with self.assertRaises(HTTPException) as not_wrong:
                add_wrong_answer_to_review(db, result["id"], question_ids[0], "owner")
            self.assertEqual(not_wrong.exception.status_code, 400)
            with self.assertRaises(HTTPException) as denied_card:
                add_wrong_answer_to_review(db, result["id"], question_ids[2], "other")
            self.assertEqual(denied_card.exception.status_code, 404)
            card_result = add_wrong_answer_to_review(db, result["id"], question_ids[2], "owner")
            self.assertTrue(card_result["created"])
            card = db.get(ReviewCard, card_result["card_id"])
            self.assertEqual((card.status, card.lesson_id, card.source_segment_id), ("review", "l1", "s1"))
            again = add_wrong_answer_to_review(db, result["id"], question_ids[2], "owner")
            self.assertEqual(again, {"card_id": card.id, "created": False})


if __name__ == "__main__":
    unittest.main()

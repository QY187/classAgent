import json
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.modules.review_cards import service  # noqa: E402
from app.modules.review_cards.schemas import CardCreate, CardReview, CardUpdate  # noqa: E402
from app.shared.models import Course, Lesson, LessonSummary, TranscriptSegment  # noqa: E402


class ReviewCardTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.lesson = Lesson(course=Course(name="数据结构", owner_username="alice"), title="二叉树")
        other = Lesson(course=Course(name="其他课程", owner_username="bob"), title="别人的课")
        self.segment = TranscriptSegment(lesson=self.lesson, speaker="说话人 1", start_ms=56000, end_ms=61000, text="叶子节点没有孩子")
        self.other_segment = TranscriptSegment(lesson=other, speaker="说话人 1", start_ms=0, end_ms=1000, text="其他内容")
        self.db.add_all([self.segment, self.other_segment])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_review_update_delete_and_source(self):
        card = service.create_card(self.db, self.lesson.id, CardCreate(title="叶子节点", body="没有孩子的节点", source_segment_id=self.segment.id), "alice")
        self.assertEqual((card["source_start_ms"], card["source_excerpt"], card["status"]), (56000, "叶子节点没有孩子", "new"))
        self.assertEqual(len(service.list_due_cards(self.db, "alice")), 1)
        self.assertEqual(service.list_due_cards(self.db, "bob"), [])

        updated = service.update_card(self.db, card["id"], CardUpdate(body="孩子数为零"), "alice")
        self.assertEqual(updated["body"], "孩子数为零")
        mastered = service.review_card(self.db, card["id"], CardReview(status="mastered"), "alice")
        self.assertEqual(mastered["status"], "mastered")
        self.assertGreater((mastered["next_review_at"] - mastered["last_reviewed_at"]).days, 6)
        self.assertEqual(service.list_due_cards(self.db, "alice"), [])
        self.assertEqual([item["id"] for item in service.list_cards(self.db, "alice")], [card["id"]])
        self.assertEqual(service.list_cards(self.db, "bob"), [])

        service.delete_card(self.db, card["id"], "alice")
        self.assertEqual(service.list_lesson_cards(self.db, self.lesson.id, "alice"), [])

    def test_reject_other_users_and_cross_lesson_source(self):
        with self.assertRaises(HTTPException) as denied:
            service.list_lesson_cards(self.db, self.lesson.id, "bob")
        self.assertEqual(denied.exception.status_code, 404)

        with self.assertRaises(HTTPException) as wrong_source:
            service.create_card(self.db, self.lesson.id, CardCreate(title="错误来源", body="正文", source_segment_id=self.other_segment.id), "alice")
        self.assertEqual(wrong_source.exception.status_code, 400)

    def test_generate_from_summary_is_cited_and_idempotent(self):
        summary = LessonSummary(lesson_id=self.lesson.id, status="completed", content=json.dumps({
            "key_concepts": [
                {"term": "叶子节点", "definition": "没有孩子的节点", "importance": "用于计数", "source_indexes": [1]},
                {"term": "无来源", "definition": "不能建卡", "source_indexes": [99]},
            ]
        }))
        self.db.add(summary)
        self.db.commit()

        result = service.create_from_summary(self.db, self.lesson.id, "alice")
        self.assertEqual(result, {"created": 1, "skipped": 1})
        card = service.list_lesson_cards(self.db, self.lesson.id, "alice")[0]
        self.assertEqual((card["title"], card["source_segment_id"], card["source_start_ms"]), ("叶子节点", self.segment.id, 56000))
        self.assertEqual(service.create_from_summary(self.db, self.lesson.id, "alice"), {"created": 0, "skipped": 2})

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.courses.overview import get_overview
from app.shared.models import ChatConversation, ChatMessage, Course, Lesson, LessonSummary, Quiz, QuizAttempt, ReviewCard, User


def at(day):
    return datetime(2026, 10, day, tzinfo=timezone.utc)


class HomeOverviewTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(id="u", username="owner", password_hash="x"), User(id="v", username="other", password_hash="x")])
        self.db.flush()
        self.db.add_all([Course(id="c", owner_id="u", name="课程"), Course(id="d", owner_id="v", name="其他")])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_empty_and_no_background_activity(self):
        self.db.add(Lesson(id="l", course_id="c", title="课次", status="completed"))
        self.db.flush()
        self.db.add(LessonSummary(lesson_id="l", status="completed", content="内容"))
        self.db.commit()
        self.assertEqual(get_overview(self.db, "owner"), {"pending_lessons": 0, "recent_learning": None})

    def test_pending_includes_empty_failed_and_missing_or_blank_summary_once(self):
        for identity, state in [("empty", "created"), ("failed", "failed"), ("missing", "completed"), ("blank", "completed"), ("ready", "completed"), ("running", "transcribing")]:
            self.db.add(Lesson(id=identity, course_id="c", title=identity, status=state))
        self.db.flush()
        self.db.add_all([LessonSummary(lesson_id="blank", status="completed", content="  "),
                         LessonSummary(lesson_id="ready", status="edited", content="有内容"),
                         LessonSummary(lesson_id="running", status="completed", content="旧内容")])
        self.db.commit()
        self.assertEqual(get_overview(self.db, "owner")["pending_lessons"], 5)

    def test_other_users_and_recycled_lessons_or_courses_hidden(self):
        self.db.add_all([Lesson(id="other", course_id="d", title="其他"),
                         Lesson(id="deleted", course_id="c", title="删除", deleted_at=at(1))])
        self.db.add(Course(id="recycled", owner_id="u", name="回收", deleted_at=at(1)))
        self.db.flush()
        self.db.add(Lesson(id="child", course_id="recycled", title="子课次"))
        self.db.commit()
        self.assertEqual(get_overview(self.db, "owner")["pending_lessons"], 0)

    def seed_activity(self):
        self.db.add(Lesson(id="l", course_id="c", title="课次"))
        self.db.add(Quiz(id="q", course_id="c", title="小测"))
        self.db.add_all([ChatConversation(id="chat", user_id="u", title="问答"), ChatConversation(id="other-chat", user_id="v")])
        self.db.flush()
        self.db.add_all([QuizAttempt(id="a", quiz_id="q", user_id="u", correct_count=3, total_count=5, created_at=at(1)),
                         QuizAttempt(id="other-a", quiz_id="q", user_id="v", correct_count=0, total_count=5, created_at=at(4)),
                         ReviewCard(id="card", lesson_id="l", course_id="c", title="知识点", body="内容", last_reviewed_at=at(2)),
                         ChatMessage(id="msg", conversation_id="chat", position=1, request_id="r", role="user", status="completed", content="提问", created_at=at(3)),
                         ChatMessage(conversation_id="other-chat", position=1, request_id="r", role="user", content="别人", created_at=at(4))])
        self.db.commit()

    def test_latest_completed_chat_not_failed_messages(self):
        self.seed_activity()
        self.db.add(ChatMessage(conversation_id="chat", position=2, request_id="fail", role="user", status="failed", content="失败", created_at=at(4)))
        self.db.commit()
        recent = get_overview(self.db, "owner")["recent_learning"]
        self.assertEqual(recent["kind"], "chat")
        self.assertEqual(recent["href"], "/chat?conversation=chat")
        self.assertTrue(recent["at"].endswith("+00:00"))

    def test_archived_chat_falls_back_to_review(self):
        self.seed_activity()
        self.db.get(ChatConversation, "chat").is_archived = True
        self.db.commit()
        recent = get_overview(self.db, "owner")["recent_learning"]
        self.assertEqual(recent["kind"], "review")
        self.assertEqual(recent["href"], "/lessons/l/review")

    def test_deleted_review_lesson_falls_back_to_quiz(self):
        self.seed_activity()
        self.db.get(ChatConversation, "chat").is_archived = True
        self.db.get(Lesson, "l").deleted_at = at(4)
        self.db.commit()
        recent = get_overview(self.db, "owner")["recent_learning"]
        self.assertEqual(recent["kind"], "quiz")
        self.assertEqual(recent["href"], "/quiz-attempts/a")

    def test_recycled_course_hides_all_attached_activity(self):
        self.seed_activity()
        self.db.get(ChatConversation, "chat").course_id = "c"
        self.db.get(Course, "c").deleted_at = at(4)
        self.db.commit()
        self.assertIsNone(get_overview(self.db, "owner")["recent_learning"])

import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import Base  # noqa: E402
from app.modules.search.mapper import search_all  # noqa: E402
from app.shared.models import Course, Lesson, ReviewCard, User  # noqa: E402


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        alice = User(id="alice-id", username="alice", password_hash="test")
        bob = User(id="bob-id", username="bob", password_hash="test")
        alice_lesson = Lesson(course=Course(id="alice-course", name="数据结构", owner_id=alice.id, owner_username=alice.username), title="二叉树")
        bob_lesson = Lesson(course=Course(id="bob-course", name="别人的课程", owner_id=bob.id, owner_username=bob.username), title="别人的课次")
        self.db.add_all([
            alice, bob,
            ReviewCard(course_id=alice_lesson.course.id, lesson=alice_lesson, title="满二叉树", body="每层节点数达到上限"),
            ReviewCard(course_id=alice_lesson.course.id, lesson=alice_lesson, title="节点数量", body="二叉树的节点数量有上界"),
            ReviewCard(course_id="alice-course-2", lesson=Lesson(course=Course(id="alice-course-2", name="算法", owner_id=alice.id, owner_username=alice.username), title="树结构"), title="二叉树练习", body="更多练习"),
            ReviewCard(course_id=bob_lesson.course.id, lesson=bob_lesson, title="满二叉树", body="不应被其他用户搜索到"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_search_card_title_and_body_respects_owner(self):
        title_matches = search_all(self.db, "满二叉树", "alice")["review_cards"]
        self.assertEqual(len(title_matches), 1)
        self.assertEqual((title_matches[0]["course_name"], title_matches[0]["lesson_title"]), ("数据结构", "二叉树"))

        body_matches = search_all(self.db, "上界", "alice")["review_cards"]
        self.assertEqual([item["title"] for item in body_matches], ["节点数量"])
        self.assertIn("上界", body_matches[0]["snippet"])

    def test_filters_apply_before_result_limit(self):
        results = search_all(self.db, "二叉树", "alice", course_id="alice-course-2", kind="review_cards")
        self.assertEqual([item["title"] for item in results["review_cards"]], ["二叉树练习"])
        self.assertEqual(results["courses"], [])
        self.assertEqual(results["transcript"], [])
        self.assertEqual(search_all(self.db, "二叉树", "alice", course_id="bob-course")["review_cards"], [])

    def test_lesson_result_names_its_course(self):
        lessons = search_all(self.db, "二叉树", "alice", kind="lessons")["lessons"]
        self.assertEqual([(item["title"], item["course_name"]) for item in lessons], [("二叉树", "数据结构")])

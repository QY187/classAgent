import unittest

from app.modules.courses.overview import get_overview
from app.modules.courses.pending import list_pending_lessons
from app.shared.models import Course, Lesson, LessonSummary, ProcessingJob
from test_home_overview import HomeOverviewTest, at


class PendingLessonsTest(unittest.TestCase):
    setUp = HomeOverviewTest.setUp
    tearDown = HomeOverviewTest.tearDown

    def test_counts_and_stages_match_home(self):
        for identity, state in [("upload", "created"), ("queue", "queued"), ("working", "transcribing"), ("failed", "failed"),
                                ("summary-queue", "completed"), ("generating", "completed"), ("summary-fail", "completed"),
                                ("stale", "completed"), ("blank", "completed"), ("ready", "completed")]:
            self.db.add(Lesson(id=identity, course_id="c", title=identity, status=state))
        self.db.flush()
        for identity, state, content in [("summary-queue", "queued", None), ("generating", "generating", None),
                                          ("summary-fail", "failed", None), ("stale", "stale", None),
                                          ("blank", "completed", "  "), ("ready", "edited", "内容")]:
            self.db.add(LessonSummary(lesson_id=identity, status=state, content=content, error_message="纪要服务暂不可用" if state == "failed" else None))
        self.db.add(ProcessingJob(lesson_id="failed", stage="failed", error_message="音频格式无法识别"))
        self.db.commit()
        page = list_pending_lessons(self.db, "owner")
        items = {item["id"]: item for item in page["items"]}
        self.assertEqual(page["total"], get_overview(self.db, "owner")["pending_lessons"])
        self.assertEqual(page["total"], 9)
        self.assertNotIn("ready", items)
        self.assertEqual(items["upload"]["stage_label"], "等待录音或上传")
        self.assertEqual(items["queue"]["stage_label"], "等待转写")
        self.assertEqual(items["working"]["stage_label"], "正在转写")
        self.assertEqual(items["failed"]["error_message"], "音频格式无法识别")
        self.assertEqual(items["summary-queue"]["stage_label"], "等待生成纪要")
        self.assertEqual(items["generating"]["stage_label"], "正在生成纪要")
        self.assertEqual(items["summary-fail"]["error_message"], "纪要服务暂不可用")
        self.assertEqual(items["stale"]["stage_label"], "纪要需要更新")
        self.assertEqual(items["blank"]["stage_label"], "尚无可用纪要")

    def test_paging_stable_and_latest_job_only(self):
        self.db.add_all([Lesson(id=identity, course_id="c", title=identity, status="failed", created_at=at(1)) for identity in ("a", "b", "z")])
        self.db.flush()
        self.db.add_all([ProcessingJob(id="old", lesson_id="z", stage="failed", error_message="旧失败", created_at=at(1)),
                         ProcessingJob(id="new", lesson_id="z", stage="failed", error_message="最新失败", created_at=at(2))])
        self.db.commit()
        page = list_pending_lessons(self.db, "owner", limit=2)
        next_page = list_pending_lessons(self.db, "owner", offset=2, limit=2)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["items"][0]["error_message"], "最新失败")
        self.assertTrue(page["has_more"])
        self.assertFalse(next_page["has_more"])
        self.assertEqual(len({item["id"] for item in page["items"] + next_page["items"]}), 3)

    def test_old_failure_not_shown_during_retry_or_after_transcription(self):
        self.db.add_all([Lesson(id="running", course_id="c", title="重试", status="transcribing"),
                         Lesson(id="completed", course_id="c", title="已转写", status="completed")])
        self.db.flush()
        self.db.add_all([ProcessingJob(lesson_id=identity, stage="failed", error_message="旧失败") for identity in ("running", "completed")])
        self.db.commit()
        items = list_pending_lessons(self.db, "owner")["items"]
        self.assertTrue(all(item["error_message"] is None for item in items))

    def test_other_users_and_recycled_records_hidden(self):
        self.db.add_all([Lesson(id="other", course_id="d", title="其他"), Lesson(id="gone", course_id="c", title="已删", deleted_at=at(1))])
        self.db.add(Course(id="deleted-course", owner_id="u", name="已删课程", deleted_at=at(1)))
        self.db.flush()
        self.db.add(Lesson(id="child", course_id="deleted-course", title="已删子课次"))
        self.db.commit()
        self.assertEqual(list_pending_lessons(self.db, "owner")["items"], [])
        self.assertEqual(list_pending_lessons(self.db, "owner")["total"], 0)

    def test_missing_failure_reason_fallback_and_links(self):
        self.db.add(Lesson(id="failure", course_id="c", title="失败课次", status="failed"))
        self.db.commit()
        item = list_pending_lessons(self.db, "owner")["items"][0]
        self.assertIn("未记录具体原因", item["error_message"])
        self.assertEqual(item["href"], "/lessons/failure")
        self.assertEqual(item["course_name"], "课程")

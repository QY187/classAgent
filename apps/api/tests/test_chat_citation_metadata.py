import unittest
from sqlalchemy.orm import Session
from test_recycle_visibility import RecycleVisibilityTest
from app.modules.chat.messages import enrich_citations
from app.shared.models import Course, Lesson, User, now_utc

class CitationMetadataTest(unittest.TestCase):
    setUp = RecycleVisibilityTest.setUp
    tearDown = RecycleVisibilityTest.tearDown
    def test_course_names_only_come_from_visible_owned_sources(self):
        with Session(self.engine) as db:
            db.add(User(id="other",username="other",password_hash="x")); db.flush()
            db.add(Course(id="foreign",owner_id="other",name="他人课程")); db.flush()
            db.add(Lesson(id="foreign-lesson",course_id="foreign",title="他人课次")); db.commit()
            citations=[{"id":1,"lesson_id":"l","start_ms":0,"end_ms":1000},
                       {"id":2,"lesson_id":"foreign-lesson","start_ms":0},
                       {"id":3,"source_type":"material","course_id":"c"}]
            result=enrich_citations(db,citations,"u")
            self.assertEqual(result[0]["course_name"],"数据结构")
            self.assertEqual(result[0]["end_ms"],1000)
            self.assertNotIn("course_name",result[1])
            self.assertEqual(result[1]["source_status"],"unavailable")
            self.assertEqual(result[2]["course_name"],"数据结构")
            db.get(Lesson,"l").deleted_at=now_utc();db.commit()
            hidden=enrich_citations(db,[{"lesson_id":"l","start_ms":0}],"u")[0]
            self.assertNotIn("course_name",hidden)
            self.assertEqual(hidden["source_status"],"unavailable")

import unittest
import test_recycle_visibility as fixtures
from unittest.mock import patch
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.shared.models import DocumentChunk, Lesson
from app.modules.rag.service import ask_course, chunk_scope


class ChatScopeTest(unittest.TestCase):
    setUp = fixtures.RecycleVisibilityTest.setUp
    tearDown = fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.rag.service.get_settings", return_value=SimpleNamespace(deepseek_api_key="test"))
    @patch("app.modules.rag.service.embed_texts")
    def test_other_lesson_chunks_are_never_used(self, embed, settings):
        with Session(self.engine) as db:
            db.add(Lesson(id="another", course_id="c", title="其他课次")); db.flush()
            db.add(DocumentChunk(course_id="c", lesson_id="another", kind="transcript", content="其他课次", start_ms=0,
                                 end_ms=1, source_segment_ids="[]", embedding=[0.0] * 1536)); db.commit()
            self.assertEqual(list(db.scalars(select(DocumentChunk).where(*chunk_scope("c", "l")))), [])
            result = ask_course(db, "c", "owner", "课堂问题", lesson_id="l")
            self.assertIn("本课次", result["answer"])
            embed.assert_not_called()
            with self.assertRaises(HTTPException):
                ask_course(db, "c", "owner", "课堂问题", lesson_id="missing")

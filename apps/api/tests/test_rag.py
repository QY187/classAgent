import json
import unittest
from types import SimpleNamespace

from app.modules.rag.indexing import make_chunks
from app.modules.rag.service import ground_claims


def segment(identifier: str, start: int, text: str):
    return SimpleNamespace(id=identifier, speaker="老师", start_ms=start, end_ms=start + 1000, text=text)


class RagTest(unittest.TestCase):
    def test_chunks_keep_lesson_time_and_original_segment_ids(self):
        segments = [segment("a", 1000, "前序先访问根节点"), segment("b", 2000, "再访问左子树")]
        summary = json.dumps({
            "topics": [
                {"title": "前序遍历", "summary": "先根后左", "source_indexes": [1, 2]},
                {"title": "无来源结论", "summary": "不应入库", "source_indexes": []},
            ]
        })
        chunks = make_chunks(segments, summary)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["kind"], "transcript")
        self.assertEqual(chunks[0]["start_ms"], 1000)
        self.assertEqual(chunks[0]["source_segment_ids"], ["a", "b"])
        self.assertEqual(chunks[1]["kind"], "summary")
        self.assertEqual(chunks[1]["source_segment_ids"], ["a", "b"])
        self.assertTrue(all("无来源结论" not in chunk["content"] for chunk in chunks))

    def test_empty_transcript_does_not_make_unanchored_summary_chunks(self):
        self.assertEqual(make_chunks([], '{"topics":[{"title":"空资料","source_indexes":[1]}]}'), [])

    def test_answer_discards_claims_without_real_evidence(self):
        evidence = {"S1": SimpleNamespace(lesson_id="lesson-1", start_ms=2000, end_ms=3000, content="老师：先访问根节点", source_segment_ids='["a"]')}
        lessons = {"lesson-1": SimpleNamespace(title="第一讲")}
        answer = ground_claims([
            {"text": "无依据的回答", "source_ids": ["S99"]},
            {"text": "先访问根节点", "source_ids": ["S1"]},
        ], evidence, lessons)
        self.assertNotIn("无依据", answer["answer"])
        self.assertEqual(answer["citations"][0]["start_ms"], 2000)
        self.assertEqual(answer["citations"][0]["segment_ids"], ["a"])

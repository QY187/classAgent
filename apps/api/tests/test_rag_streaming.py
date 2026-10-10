import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from app.modules.rag.streaming import ClaimStream, stream_completion
from app.modules.rag.service import ground_claims


class RagStreamingTest(unittest.TestCase):
    def test_split_json_and_escaped_quotes_only_emit_complete_claims(self):
        raw = json.dumps({"claims": [{"text": '结论含"引号"与括号}', "source_ids": ["S1"]},
                                      {"text": "第二条", "source_ids": ["S2"]}]}, ensure_ascii=False)
        parser = ClaimStream()
        counts = []
        for character in raw:
            if parser.feed(character):
                counts.append(len(parser.claims))
        self.assertEqual(counts, [1, 2])
        self.assertEqual(parser.claims, json.loads(raw)["claims"])

    def test_unprovided_sources_never_appear_in_preview(self):
        parser = ClaimStream()
        parser.feed('{"claims":[{"text":"无依据","source_ids":["S9"]},{"text":"有依据","source_ids":["S1"]}]}')
        item = SimpleNamespace(lesson_id="l", start_ms=0, end_ms=1, content="原文", source_segment_ids="[]")
        result = ground_claims(parser.claims, {"S1": item}, {"l": SimpleNamespace(title="课堂")})
        self.assertNotIn("无依据", result["answer"])
        self.assertEqual(result["answer"], "有依据 [1]")

    @patch("app.modules.rag.streaming.httpx.stream")
    def test_upstream_disconnect_is_failure_even_with_partial_claims(self, stream):
        response = Mock()
        stream.return_value.__enter__.return_value = response
        response.iter_lines.return_value = iter(['data: ' + json.dumps({"choices": [{"delta": {"content": '{"claims":[{"text":"片段","source_ids":["S1"]}'}}]})])
        preview = Mock()
        with self.assertRaises(ValueError):
            stream_completion("url", {}, {}, preview)
        preview.assert_called_once()

    @patch("app.modules.rag.streaming.httpx.stream")
    def test_stream_finishes_and_returns_full_json(self, stream):
        raw = '{"claims":[]}'
        response = Mock()
        stream.return_value.__enter__.return_value = response
        response.iter_lines.return_value = iter([': keepalive', 'data: ' + json.dumps({"choices": [{"delta": {"content": raw}}]}), 'data: [DONE]'])
        self.assertEqual(stream_completion("url", {}, {}, Mock()), raw)


if __name__ == "__main__":
    unittest.main()

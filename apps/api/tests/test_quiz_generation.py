from types import SimpleNamespace
from unittest.mock import patch

from app.modules.quizzes.generation import source_batches, stem_key
from app.modules.quizzes.service import _generate_questions


def test_windows_include_long_segment_tail_and_short_lesson():
    sources = [SimpleNamespace(id="long", lesson_id="long", text="甲" * 150000 + "尾部重要结论"),
               SimpleNamespace(id="short", lesson_id="short", text="短课的定义")]
    batches = source_batches(sources)
    windows = [row for batch in batches for row in batch]
    assert len(windows) == 90
    assert len(batches) == 6
    assert any("尾部重要结论" in row.text for row in windows)
    assert any(row.lesson_id == "short" for row in windows)
    assert max(len(row.text) for row in windows) <= 1000


def test_refill_deduplicates_and_keeps_original_source():
    source = SimpleNamespace(id="s", lesson_id="l", text="课堂定义与依据")
    calls = []
    def request(batch, count, kind, **kwargs):
        calls.append(kwargs)
        stems = ["概念Ａ？", "概念A！", "定义B", "定义C"] if len(calls) == 1 else ["定义D", "定义E"]
        return [dict(stem=stem, kind="true_false", source=batch[0]) for stem in stems]
    with patch("app.modules.quizzes.service._request_questions", side_effect=request):
        result = _generate_questions([source], 5, "true_false")
    assert len(result) == 5
    assert len(calls) == 2
    assert calls[1]["excluded_stems"]
    assert all(item["source"] is source for item in result)
    assert stem_key("概念Ａ？") == stem_key("概念A！")

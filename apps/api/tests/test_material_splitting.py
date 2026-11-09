"""验证自然边界、递归降级、内容保真与来源位置，而非固定长度截断。"""
import pytest

from app.modules.materials.extraction import make_material_chunks
from app.modules.materials.splitting import recursive_character_chunks


def split(text, size=20, overlap=0):
    return recursive_character_chunks(text, chunk_size=size, chunk_overlap=overlap)


def test_paragraph_boundaries_have_priority_over_sentences():
    paragraphs = ["第一段。还有解释。\n\n", "第二段。还有例子。\n\n", "第三段。结束。"]
    assert split("".join(paragraphs)) == [paragraphs[0], paragraphs[1] + paragraphs[2]]


def test_only_oversized_paragraph_recurses_to_sentences():
    first = "短段落。\n\n"
    sentences = ["二叉树每个结点最多有两个孩子。", "叶子结点没有孩子。", "前序遍历先访问根结点。"]
    chunks = split(first + "".join(sentences))
    assert chunks == [first, sentences[0], sentences[1] + sentences[2]]
    assert "".join(chunks) == first + "".join(sentences)


@pytest.mark.parametrize("text,expected", [
    ("第一行\r\n第二行\r\n第三行", ["第一行\r\n第二行\r\n", "第三行"]),
    ("甲乙丙丁；戊己庚辛；壬癸子丑", ["甲乙丙丁；戊己庚辛；", "壬癸子丑"]),
    ("甲乙丙丁，戊己庚辛，壬癸子丑", ["甲乙丙丁，戊己庚辛，", "壬癸子丑"]),
    ("alpha beta gamma delta", ["alpha beta ", "gamma delta"]),
])
def test_recursive_separator_levels_preserve_original_text(text, expected):
    assert split(text, size=11) == expected
    assert "".join(expected) == text


def test_english_sentences_keep_punctuation_and_decimal_values():
    text = "Value is 3.14. Next sentence! Final one?"
    assert split(text, size=18) == ["Value is 3.14.", " Next sentence!", " Final one?"]


def test_chinese_sentence_end_keeps_closing_quotes():
    sentences = ['他说：“最多两个。”', "但不是恰好两个！", "请注意条件？"]
    assert split("".join(sentences), size=12) == sentences


def test_overlap_keeps_whole_sentences_instead_of_cutting_characters():
    sentences = ["甲是定义。", "乙是条件。", "丙是例子。", "丁是总结。"]
    assert split("".join(sentences), size=12, overlap=6) == [
        sentences[0] + sentences[1], sentences[1] + sentences[2], sentences[2] + sentences[3]]
    # 单句超过重叠预算时允许零重叠，不强行截断句子。
    assert split("".join(sentences), size=12, overlap=3) == [
        sentences[0] + sentences[1], sentences[2] + sentences[3]]


def test_unbroken_text_falls_back_to_characters_with_bounded_overlap():
    text = "".join(chr(0x4E00 + index) for index in range(6000))
    chunks = recursive_character_chunks(text)
    assert len(chunks) == 5
    assert all(0 < len(chunk) <= 1400 for chunk in chunks)
    assert all(left[-150:] == right[:150] for left, right in zip(chunks, chunks[1:]))
    assert chunks[0] + "".join(chunk[150:] for chunk in chunks[1:]) == text


def test_sources_never_merge_and_positions_remain_contiguous():
    units = [{"locator_type": kind, "locator_number": number, "content": "定义与解释。" * 350}
             for kind, number in (("page", 2), ("slide", 7), ("paragraph", 4))]
    chunks = make_material_chunks(units)
    assert [chunk["position"] for chunk in chunks] == list(range(len(chunks)))
    for unit in units:
        selected = [chunk for chunk in chunks if chunk["locator_type"] == unit["locator_type"]]
        assert len(selected) > 1
        assert all(chunk["locator_number"] == unit["locator_number"] for chunk in selected)
        assert all(chunk["content"] in unit["content"] for chunk in selected)
        assert all(chunk["content"].endswith("。") for chunk in selected)


def test_mixed_recursive_levels_preserve_order_coverage_and_overlap_limit():
    import random
    rng = random.Random(27)
    for _ in range(30):
        pieces = []
        cursor = 0
        for _ in range(12):
            length = rng.randint(10, 1800)
            pieces.append("".join(chr(0x4E00 + index) for index in range(cursor, cursor + length)))
            pieces.append(rng.choice(["\n\n", "\r\n", "。", "！", ";", "，", " ", ""]))
            cursor += length
        text = "".join(pieces)
        chunks = recursive_character_chunks(text)
        previous_start, covered = -1, 0
        for chunk in chunks:
            start = text.find(chunk, previous_start + 1)
            assert start >= 0
            # 不单独索引纯空白片；任何未覆盖的间隔都只能是空白。
            assert not text[covered:start].strip()
            assert max(0, covered - start) <= 150
            assert 0 < len(chunk) <= 1400
            previous_start, covered = start, start + len(chunk)
        assert text[covered:].strip() == ""


@pytest.mark.parametrize("text", ["", " \r\n\t", "短段落。", "a" * 1400])
def test_empty_short_and_exact_limit(text):
    assert recursive_character_chunks(text) == ([text] if text.strip() else [])


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, -1), (10, 10)])
def test_invalid_chunk_settings(size, overlap):
    with pytest.raises(ValueError):
        split("原文", size=size, overlap=overlap)

"""PDF排版回归：题目完整分页、中文断行和四类页眉。"""
from io import BytesIO

from pypdf import PdfReader
import pytest

from app.modules.exports.pdf import render_pdf
from app.modules.exports.render import md


def pages(data):
    return [page.extract_text() for page in PdfReader(BytesIO(data)).pages]


@pytest.mark.parametrize('kind,label', [('summary','智能纪要'),('knowledge','知识点'),('quiz','小测题目'),('transcript','文字记录'),('index','课程目录')])
def test_document_identity_and_escaped_title_are_preserved(kind,label):
    title = '第一讲 A < B & 数据结构'
    content = f'# {md(title)} · {label}\n\n正文完整保留。'
    result = pages(render_pdf(content,document_type=kind))
    assert len(result) == 1
    assert title in result[0]
    assert label in result[0] and 'ClassAgent  /  学习资料' in result[0]
    assert '正文完整保留。' in result[0] and '1 / 1' in result[0]


def test_short_question_and_all_options_stay_on_same_page():
    content = '# 二叉树练习\n\n' + '\n\n'.join(
        f'## 第 {i} 题 · 单选\n\n题干标记Q{i}：请选择正确的遍历顺序。\n\n'
        + '\n'.join(f'- {letter}. 选项标记Q{i}{letter}：根节点与左右子树。' for letter in 'ABCD')
        for i in range(1,13))
    result = pages(render_pdf(content,document_type='quiz'))
    assert len(result) > 1
    for i in range(1,13):
        containing = [text for text in result if f'题干标记Q{i}：' in text]
        assert len(containing) == 1
        assert all(f'选项标记Q{i}{letter}：' in containing[0] for letter in 'ABCD')
    for i,text in enumerate(result,1):
        assert f'{i} / {len(result)}' in text and 'ClassAgent  /  学习资料' in text


def test_chinese_punctuation_does_not_start_body_lines():
    body = '我们先从根节点出发，逐一访问左右子树；遇到空节点时，需要结束当前递归并返回上一层。' * 35
    content = '递归与遍历\n上课日期：2026-11-22\n\n001  00:00 - 00:45  |  老师\n' + body
    result = pages(render_pdf(content,plain=True,document_type='transcript'))
    assert len(result)>1
    for text in result:
        assert all(not line.lstrip().startswith(tuple('，；：！？、。）》】”’')) for line in text.splitlines() if line.strip())
    assert sum(text.count('老师') for text in result)==1

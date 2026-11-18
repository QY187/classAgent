"""离线可读的Markdown与TXT；不把资料中的HTML当作可执行内容。"""
from html.parser import HTMLParser
import json
import re


def md(value):
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", str(value or ""))


def clock(milliseconds):
    seconds = max(0, int(milliseconds or 0) // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class RichMarkdown(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.lists = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked += 1
            return
        if self.blocked:
            return
        if tag in {"h1", "h2", "h3"}:
            self.parts.append("\n\n" + "#" * (int(tag[1]) + 1) + " ")
        elif tag == "p" and self.lists and self.parts and re.search(r"(?:- |\d+\. |\[[ x]\] )$", self.parts[-1]):
            return
        elif tag in {"p", "blockquote"}:
            self.parts.append("\n\n" + ("> " if tag == "blockquote" else ""))
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "hr":
            self.parts.append("\n\n---\n\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag in {"ul", "ol"}:
            self.lists.append([tag, 0])
        elif tag == "li":
            ordered = self.lists and self.lists[-1][0] == "ol"
            if self.lists:
                self.lists[-1][1] += 1
            marker = f"{self.lists[-1][1]}. " if ordered else "- "
            if "data-checked" in attrs:
                marker = "- [x] " if attrs["data-checked"] == "true" else "- [ ] "
            self.parts.append("\n" + "  " * max(0, len(self.lists) - 1) + marker)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked = max(0, self.blocked - 1)
            return
        if self.blocked:
            return
        if tag in {"ul", "ol"} and self.lists:
            self.lists.pop()
            self.parts.append("\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag in {"h1", "h2", "h3", "p", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(md(data))


def summary_markdown(content, status):
    if not content:
        return "暂无已保存的智能纪要。\n"
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        parser = RichMarkdown()
        parser.feed(content)
        return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip() + "\n"
    if not isinstance(data, dict):
        return "纪要格式无法读取，请在应用中核对。\n"
    lines = []
    if data.get("overview"):
        lines += ["## 概览", "", md(data["overview"]), ""]
    simple = [("学习目标", "learning_goals"), ("关键结论", "key_takeaways"), ("老师强调", "teacher_emphasis"),
              ("作业与后续安排", "assignments"), ("课堂问题", "questions"), ("复习自测", "review_questions"), ("待核对内容", "to_verify")]
    for title, key in simple:
        if isinstance(data.get(key), list) and data[key]:
            lines += [f"## {title}", "", *["- " + md(value) for value in data[key]], ""]
    detailed = [("章节脉络", "chapter_flow", "title", [("时间", "time_range"), ("内容", "summary")]),
                ("主题与重点", "topics", "title", [("时间", "time_range"), ("内容", "summary"), ("要点", "points"), ("记住", "takeaway")]),
                ("核心概念", "key_concepts", "term", [("定义", "definition"), ("重要性", "importance")]),
                ("例题与案例", "examples", "title", [("背景", "context"), ("思路", "explanation"), ("结论", "conclusion")])]
    for title, key, heading, fields in detailed:
        if not isinstance(data.get(key), list) or not data[key]:
            continue
        lines += [f"## {title}", ""]
        for item in data[key]:
            if not isinstance(item, dict):
                continue
            lines += ["### " + md(item.get(heading, title)), ""]
            for label, field in fields:
                value = item.get(field)
                if isinstance(value, list):
                    lines += ["- " + md(point) for point in value]
                elif value:
                    lines += [f"**{label}**：{md(value)}", ""]
    if data.get("keywords"):
        lines += ["**关键词**：" + "、".join(md(word) for word in data["keywords"])]
    return "\n".join(lines).strip() + "\n" if lines else "暂无可读取的纪要正文。\n"


def transcript_text(lesson, segments, aliases):
    lines = [lesson.title, "ClassAgent · 课堂文字记录", f"上课日期：{lesson.lesson_date or '未设置'}", f"文字片段：{len(segments)} 段", ""]
    for index, segment in enumerate(segments, 1):
        speaker = aliases.get(segment.speaker) or segment.speaker or "未标记说话人"
        lines += [f"{index:03}  {clock(segment.start_ms)} - {clock(segment.end_ms)}  |  {speaker}", segment.text, ""]
    if not segments:
        lines.append("暂无文字记录。")
    return "\n".join(lines).rstrip() + "\n"

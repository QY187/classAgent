"""知识点和小测题目按已核对的课次范围分组。"""
from collections import defaultdict
from urllib.parse import quote
import json
from sqlalchemy import select
from ...shared.models import Quiz, ReviewCard
from .render import clock, md

CARD_STATUS = {"new": "未学习", "review": "需要复习", "mastered": "已掌握"}
CARD_TYPE = {"concept": "知识点", "question": "问答", "rule": "公式或规则", "pitfall": "易错点"}


def quoted(text):
    return "\n".join("> " + md(line) for line in (text or "").splitlines())


def knowledge_markdown(lesson, cards):
    lines = [f"# {md(lesson.title)} · 知识点", "", f"共 {len(cards)} 张卡片；掌握状态为导出时记录。", ""]
    for index, card in enumerate(cards, 1):
        lines += [f"## {index}. {md(card.title)}", "", f"类型：{CARD_TYPE.get(card.card_type, '知识点')} · 状态：{CARD_STATUS.get(card.status, '未学习')}", "", md(card.body), ""]
        if card.source_excerpt:
            lines += [f"课堂来源（保存时摘录） · {clock(card.source_start_ms)}", "", quoted(card.source_excerpt), ""]
    if not cards:
        lines += ["本课次暂无已保存的知识点。", ""]
    return "\n".join(lines)


def quiz_scope(quiz):
    try:
        ids = json.loads(quiz.lesson_ids_json) if quiz.lesson_ids_json else ([quiz.lesson_id] if quiz.lesson_id else [])
    except (ValueError, TypeError):
        return None
    return ids if isinstance(ids, list) and all(isinstance(value, str) for value in ids) else None


def quiz_markdown(quiz, titles):
    questions = list(quiz.questions)
    scope = quiz_scope(quiz)
    label = "整门课程" if scope == [] else "、".join(titles.get(identity, "课次已不可用") for identity in scope) if scope else "范围记录无法读取"
    lines = ["# " + md(quiz.title), "", f"范围：{md(label)}", f"题量：{len(questions)} · 练习版，不含答案与解析", "", "请先独立作答。", ""]
    for index, question in enumerate(questions, 1):
        try:
            options = json.loads(question.options_json)
            assert isinstance(options, list) and all(isinstance(option, str) for option in options)
        except (ValueError, TypeError, AssertionError):
            options = []
        lines += [f"## 第 {index} 题 · {'判断' if question.kind == 'true_false' else '单选'}", "", md(question.stem), ""]
        lines += [f"- {chr(65 + position)}. {md(option)}" for position, option in enumerate(options)]
        if not options:
            lines += ["选项格式无法读取，请在应用中核对。"]
        lines += [""]
    return "\n".join(lines)


class Extras:
    def __init__(self, db, course, lessons, payload, username):
        self.db, self.course, self.payload, self.username = db, course, payload, username
        self.titles = {lesson.id: lesson.title for lesson in lessons}
        self.cards, self.quizzes = (defaultdict(list) for _ in range(2))
        ids = list(self.titles)
        contents = payload.contents
        if contents.knowledge:
            for card in db.scalars(select(ReviewCard).where(ReviewCard.course_id == course.id, ReviewCard.lesson_id.in_(ids)).order_by(ReviewCard.created_at, ReviewCard.id)):
                self.cards[card.lesson_id].append(card)
        if contents.quizzes:
            for quiz in db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at, Quiz.id)):
                scope = quiz_scope(quiz)
                # 多课次题组也不能带入未选中或回收站课次的题目。
                if scope is None or (scope and not set(scope).issubset(ids)) or any(q.source_lesson_id and q.source_lesson_id not in ids for q in quiz.questions):
                    continue
                if payload.lesson_ids is not None and not scope:
                    continue
                key = scope[0] if scope and len(scope) == 1 and scope[0] in self.titles else "shared"
                self.quizzes[key].append(quiz)

    def lesson(self, archive, lesson, folder):
        lines = []
        if self.payload.contents.knowledge:
            name = f"{folder}/知识点.pdf"
            archive.document(name, knowledge_markdown(lesson, self.cards[lesson.id]))
            lines.append(f"- [知识点]({quote(name)})")
        if self.payload.contents.quizzes:
            name = f"{folder}/小测题目.pdf"
            quizzes = self.quizzes[lesson.id]
            body = "\n\n---\n\n".join(quiz_markdown(quiz, self.titles) for quiz in quizzes)
            archive.document(name, body or f"# {md(lesson.title)} · 小测题目\n\n本课次暂无已保存的小测题目。跨课次或课程小测见课程公共资料。")
            lines.append(f"- [小测题目]({quote(name)})")
        return lines

    def shared(self, archive):
        if not self.quizzes["shared"]:
            return []
        name = "课程公共资料/小测题目.pdf"
        archive.document(name, "\n\n---\n\n".join(quiz_markdown(quiz, self.titles) for quiz in self.quizzes["shared"]))
        return ["## 跨课次与课程小测", "", f"- [小测题目]({quote(name)})", ""]

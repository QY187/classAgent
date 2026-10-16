"""读取已提交小测，使用真实成绩和选项呈现，独立于知识点状态及出题动作。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from ...core.visibility import visible_get
from ...shared.models import TranscriptSegment
from ..quizzes import service as quizzes
from .schemas import QuizAttemptArguments, QuizAttemptListArguments
from .tools import check_course, check_lesson, page


def accuracy(correct, total):
    return round(correct * 100 / total, 1) if total else None


def list_quiz_attempts(db, context, args):
    course_id = args.course_id or context.course_id
    quiz_title = None
    if course_id:
        check_course(db, context, course_id)
    if args.quiz_id:
        quiz = quizzes.get_quiz(db, args.quiz_id, context.username)
        check_course(db, context, quiz["course_id"])
        if course_id and quiz["course_id"] != course_id:
            raise HTTPException(404, "小测不存在")
        course_id = quiz["course_id"]
        quiz_title = quiz["title"]
    data = quizzes.list_user_attempts(db, context.username, course_id=course_id, quiz_id=args.quiz_id,
        lesson_id=context.lesson_id, query=args.query, offset=args.offset, limit=args.limit)
    for item in data["items"]:
        item["created_at"] = item["created_at"].isoformat()
        item["accuracy_percent"] = accuracy(item["correct_count"], item["total_count"])
    correct = sum(item["correct_count"] for item in data["items"])
    total = sum(item["total_count"] for item in data["items"])
    return {**data, "page_summary": {"attempt_count": len(data["items"]), "correct_count": correct,
            "total_count": total, "accuracy_percent": accuracy(correct, total)},
            "filters": args.model_dump() | {"course_id": course_id}, "quiz_title": quiz_title, "order": "newest_first"}


def get_quiz_attempt(db, context, args):
    record = quizzes.get_attempt(db, args.attempt_id, context.username)
    course = check_course(db, context, record["course_id"])
    if context.lesson_id:
        quiz = quizzes.get_quiz(db, record["quiz_id"], context.username)
        if quiz["lesson_ids"] != [context.lesson_id]:
            raise HTTPException(404, "答题记录不存在")
    items = []
    for question in record["questions"][args.offset:args.offset + args.limit]:
        item = {key: question[key] for key in ("id", "kind", "selected_option", "correct_option", "is_correct")}
        item.update(stem=question["stem"][:500], options=[option[:200] for option in question["options"]],
                    explanation=question["explanation"][:2000], source_status="unavailable", source=None)
        segment = visible_get(db, TranscriptSegment, question["source_segment_id"]) if question["source_segment_id"] else None
        if segment is not None and segment.lesson_id == question["source_lesson_id"]:
            try:
                lesson = check_lesson(db, context, segment.lesson_id)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
            else:
                if lesson.course_id == record["course_id"]:
                    excerpt = question["source_excerpt"]
                    item["source_status"] = "changed"
                    if excerpt and excerpt in segment.text:
                        item["source_status"] = "available"
                        item["source"] = {"segment_id": segment.id, "lesson_id": lesson.id, "lesson_title": lesson.title,
                                          "start_ms": segment.start_ms, "end_ms": segment.end_ms, "excerpt": excerpt[:180]}
        item["truncated"] = (len(question["stem"]) > 500 or len(question["explanation"]) > 2000
                             or any(len(option) > 200 for option in question["options"]))
        items.append(item)
    pagination = page(record["questions"], args.offset, args.limit)
    return {key: record[key] for key in ("id", "quiz_id", "course_id", "title", "correct_count", "total_count")} | {
        "course_name": course.name, "created_at": record["created_at"].isoformat(),
        "accuracy_percent": accuracy(record["correct_count"], record["total_count"]),
        "items": items, "total": pagination["total"], "next_offset": pagination["next_offset"], "filters": args.model_dump()}


READERS = {"list_quiz_attempts": (QuizAttemptListArguments, list_quiz_attempts),
           "get_quiz_attempt": (QuizAttemptArguments, get_quiz_attempt)}


def display_time(value):
    date = datetime.fromisoformat(value)
    # SQLite 可能省略时区；数据库中的无时区时间按 UTC 处理。
    return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")


def score(row):
    percent = row["accuracy_percent"]
    return f"答对 {row['correct_count']}/{row['total_count']} 题" + (f"，正确率 {percent:g}%" if percent is not None else "")


class QuizResultStore:
    def __init__(self):
        self.queries = {}

    def collect(self, name, result):
        if name not in READERS or not result["ok"]:
            return
        key = f"Q{len(self.queries) + 1}"
        self.queries[key] = (name, READERS[name][0].model_validate(result["data"]["filters"]))
        result["data"]["quiz_result_query_id"] = key

    def answer(self, db, context, selection):
        keys = selection.get("query_ids")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 8 or any(not isinstance(key, str) or key not in self.queries for key in keys):
            raise ValueError("未读取的小测成绩")
        db.expire_all()
        lines, citations = [], []
        for key in dict.fromkeys(keys):
            name, args = self.queries[key]
            data = READERS[name][1](db, context, args)
            if name == "list_quiz_attempts":
                scope = check_course(db, context, data["filters"]["course_id"]).name if data["filters"]["course_id"] else "所有课程"
                if context.lesson_id:
                    scope += " / " + check_lesson(db, context, context.lesson_id).title
                if data["quiz_title"]:
                    scope += " / " + data["quiz_title"]
                lines.append(f"{scope} · 已提交小测作答：{data['total']} 次" + (f"，小测标题搜索：{args.query}" if args.query else ""))
                if not data["items"]:
                    lines.append("没有符合条件的已提交答题记录。已生成但尚未提交的小测不计入成绩。" if not data["total"] else "当前分页没有答题记录。")
                    continue
                summary = data["page_summary"]
                label = "最近" if not args.offset else "本页"
                lines.append(f"{label} {summary['attempt_count']} 次作答合计{score(summary)}（按答题数加权）。")
                for index, row in enumerate(data["items"], args.offset + 1):
                    lines.append(f"{index}. {row['course_name']} / {row['title']} · {display_time(row['created_at'])} · {score(row)}")
            else:
                lines.append(f"{data['course_name']} / {data['title']} · {display_time(data['created_at'])} · {score(data)}")
                lines.append("以下为已提交作答及出题时保存的答案、解析；课堂来源可用于再次核对。")
                for index, row in enumerate(data["items"], args.offset + 1):
                    options = row["options"]
                    lines.append(f"{index}. {row['stem']} · {'答对' if row['is_correct'] else '答错'}\n"
                                 + "\n".join(f"{'ABCD'[i]}. {option}" for i, option in enumerate(options))
                                 + f"\n你的选择：{'ABCD'[row['selected_option']]}. {options[row['selected_option']]}"
                                 + f"\n正确答案：{'ABCD'[row['correct_option']]}. {options[row['correct_option']]}"
                                 + f"\n历史解析：{row['explanation']}")
                    if row["source_status"] == "available":
                        source = row["source"]
                        citation_id = len(citations) + 1
                        citations.append({"id": citation_id, "lesson_id": source["lesson_id"], "lesson_title": source["lesson_title"],
                            "start_ms": source["start_ms"], "end_ms": source["end_ms"], "snippet": source["excerpt"], "segment_ids": [source["segment_id"]]})
                        lines.append(f"课堂来源：{source['lesson_title']} [{citation_id}]")
                    else:
                        lines.append("原课堂文字已变化，请重新核对题目与答案。" if row["source_status"] == "changed" else "课堂来源当前不可用，无法回到原文核对。")
                    if row["truncated"]:
                        lines.append("题目内容较长，本次显示内容已截短。")
                if not data["items"]:
                    lines.append("当前分页没有题目。")
            if data["next_offset"] is not None:
                lines.append(f"本次显示第 {args.offset + 1}–{args.offset + len(data['items'])} 条，可继续查询下一页。")
        lines.append("成绩仅反映这些次作答，知识点掌握状态仍由你手动标记。")
        return {"answer": "\n\n".join(lines), "citations": citations}

"""复用学习记录服务；查询结果由后端复核呈现，不让模型编造掌握情况。"""
from collections import Counter

from fastapi import HTTPException

from ..review_cards import service as cards
from ..quizzes import service as quizzes
from .schemas import KnowledgeListArguments, WrongQuestionListArguments
from .tools import check_course, check_lesson, page


CARD_STATUSES = {"new": "未学习", "review": "需要复习", "mastered": "已掌握"}
WRONG_STATUSES = {"pending": "待巩固", "mastered": "已掌握"}


def learning_scope(db, context, args):
    course_id = args.course_id or context.course_id
    lesson_id = args.lesson_id or context.lesson_id
    if course_id:
        check_course(db, context, course_id)
    if lesson_id:
        lesson = check_lesson(db, context, lesson_id)
        if course_id and lesson.course_id != course_id:
            raise HTTPException(404, "课次不存在")
        course_id = lesson.course_id
    return course_id, lesson_id


def list_knowledge_points(db, context, args):
    course_id, lesson_id = learning_scope(db, context, args)
    rows = cards.list_lesson_cards(db, lesson_id, context.username) if lesson_id else cards.list_cards(db, context.username)
    rows = [row for row in rows if (not course_id or row["course_id"] == course_id)
            and (args.status == "all" or row["status"] == args.status)
            and args.query.casefold() in (row["title"] + "\n" + row["body"]).casefold()]
    items = [{key: row[key] for key in ("id", "course_id", "course_name", "lesson_id", "lesson_title",
              "title", "status", "source_segment_id", "source_start_ms")}
             | {"body": row["body"][:600]} for row in rows]
    return {**page(items, args.offset, args.limit), "status_counts": dict(Counter(row["status"] for row in rows)),
            "filters": args.model_dump() | {"course_id": course_id, "lesson_id": lesson_id},
            "status_origin": "user_marked"}


def list_wrong_questions(db, context, args):
    course_id, lesson_id = learning_scope(db, context, args)
    rows = [row for row in quizzes.list_wrong_questions(db, context.username, course_id)
            if (not lesson_id or row["source_lesson_id"] == lesson_id)
            and (args.status == "all" or row["status"] == args.status)
            and args.query.casefold() in row["stem"].casefold()]
    items = []
    for row in rows:
        item = {key: row[key] for key in ("id", "kind", "stem", "course_id", "course_name", "quiz_id",
                "quiz_title", "status", "wrong_count", "retry_count", "source_lesson_id", "source_start_ms")}
        item["last_wrong_at"] = row["last_wrong_at"].isoformat()
        item["last_retry_at"] = row["last_retry_at"].isoformat() if row["last_retry_at"] else None
        items.append(item)
    return {**page(items, args.offset, args.limit), "status_counts": dict(Counter(row["status"] for row in rows)),
            "filters": args.model_dump() | {"course_id": course_id, "lesson_id": lesson_id},
            "status_origin": "latest_answer"}


READERS = {"list_knowledge_points": (KnowledgeListArguments, list_knowledge_points),
           "list_wrong_questions": (WrongQuestionListArguments, list_wrong_questions)}


class LearningStore:
    def __init__(self):
        self.queries = {}

    def collect(self, name, result):
        if name not in READERS or not result["ok"]:
            return
        key = f"L{len(self.queries) + 1}"
        self.queries[key] = (name, READERS[name][0].model_validate(result["data"]["filters"]))
        result["data"]["learning_query_id"] = key

    def answer(self, db, context, selection):
        keys = selection.get("query_ids")
        if not isinstance(keys, list) or not keys or len(keys) > 8 or any(not isinstance(key, str) or key not in self.queries for key in keys):
            raise ValueError("未读取的学习记录")
        lines = []
        # 重新查询确保改状态、回收资料后的回答仍与业务页面一致。
        db.expire_all()
        for key in dict.fromkeys(keys):
            name, args = self.queries[key]
            data = READERS[name][1](db, context, args)
            scope = check_course(db, context, data["filters"]["course_id"]).name if data["filters"]["course_id"] else "所有课程"
            knowledge = name == "list_knowledge_points"
            statuses = CARD_STATUSES if knowledge else WRONG_STATUSES
            noun, unit = ("知识点", "个") if knowledge else ("错题", "道")
            label = statuses.get(args.status, "全部状态")
            heading = f"{scope} · {noun}（{label}）：{data['total']} {unit}"
            if args.query:
                heading += f"，搜索：{args.query}"
            lines.append(heading)
            origin = "状态由你手动标记。" if knowledge else "状态按最近的小测作答或错题重练结果确定。"
            lines.append(origin + "、".join(f"{label} {data['status_counts'].get(status, 0)} {unit}" for status, label in statuses.items()))
            for row in data["items"]:
                if knowledge:
                    lines.append(f"• {row['title']} · {statuses[row['status']]} · {row['course_name']} / {row['lesson_title']}")
                else:
                    lines.append(f"• {row['stem']} · {statuses[row['status']]} · {row['course_name']} / {row['quiz_title']} · 小测答错 {row['wrong_count']} 次、重练 {row['retry_count']} 次")
            if not data["items"]:
                lines.append(f"没有符合条件的{noun}。" if not data["total"] else "当前分页没有记录。")
            elif args.offset or data["next_offset"] is not None:
                lines.append(f"本次显示第 {args.offset + 1}–{args.offset + len(data['items'])} 个，可继续查询下一页。")
        return "\n\n".join(lines)

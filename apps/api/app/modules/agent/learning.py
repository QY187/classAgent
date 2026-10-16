"""复用学习记录服务；查询结果由后端复核呈现，不让模型编造掌握情况。"""
from collections import Counter

from fastapi import HTTPException

from ..review_cards import service as cards
from .schemas import KnowledgeListArguments
from .tools import check_course, check_lesson, page


CARD_STATUSES = {"new": "未学习", "review": "需要复习", "mastered": "已掌握"}


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


class LearningStore:
    def __init__(self):
        self.queries = {}

    def collect(self, name, result):
        if name != "list_knowledge_points" or not result["ok"]:
            return
        key = f"L{len(self.queries) + 1}"
        self.queries[key] = (name, KnowledgeListArguments.model_validate(result["data"]["filters"]))
        result["data"]["learning_query_id"] = key

    def answer(self, db, context, selection):
        keys = selection.get("query_ids")
        if not isinstance(keys, list) or not keys or len(keys) > 8 or any(not isinstance(key, str) or key not in self.queries for key in keys):
            raise ValueError("未读取的学习记录")
        lines = []
        # 重新查询确保改状态、回收资料后的回答仍与业务页面一致。
        db.expire_all()
        for key in dict.fromkeys(keys):
            _, args = self.queries[key]
            data = list_knowledge_points(db, context, args)
            scope = check_course(db, context, data["filters"]["course_id"]).name if data["filters"]["course_id"] else "所有课程"
            label = CARD_STATUSES.get(args.status, "全部状态")
            heading = f"{scope} · 知识点（{label}）：{data['total']} 个"
            if args.query:
                heading += f"，搜索：{args.query}"
            lines.append(heading)
            lines.append("状态由你手动标记。" + "、".join(f"{label} {data['status_counts'].get(status, 0)} 个" for status, label in CARD_STATUSES.items()))
            for row in data["items"]:
                lines.append(f"• {row['title']} · {CARD_STATUSES[row['status']]} · {row['course_name']} / {row['lesson_title']}")
            if not data["items"]:
                lines.append("没有符合条件的知识点。" if not data["total"] else "当前分页没有记录。")
            elif args.offset or data["next_offset"] is not None:
                lines.append(f"本次显示第 {args.offset + 1}–{args.offset + len(data['items'])} 个，可继续查询下一页。")
        return "\n\n".join(lines)

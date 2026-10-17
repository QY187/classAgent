"""课程进度复用业务统计；回答重新查询，不接受模型编造的数量。"""
from fastapi import HTTPException
from ..courses import service as courses
from .schemas import CourseProgressArguments
from .tools import check_course, page


SUMMARY_STATES = {"missing": "尚无纪要", "queued": "排队中", "processing": "生成中",
                  "failed": "生成失败", "stale": "已过期", "completed": "内容为空", "edited": "内容为空"}


def get_course_progress(db, context, args):
    course_id = args.course_id or context.course_id
    if not course_id:
        raise HTTPException(400, "请先指定要查询的课程")
    if context.lesson_id:
        raise HTTPException(400, "请在课程对话或主对话中查询整门课程进度")
    course = check_course(db, context, course_id)
    data = courses.get_course_progress(db, course_id, context.username)
    missing = courses.list_lessons_missing_summary(db, course_id, context.username)
    return {**data, "course_name": course.name, "missing_summaries": page(missing, args.offset, args.limit),
            "filters": args.model_dump() | {"course_id": course_id}, "status_origin": "user_marked"}


class ProgressStore:
    def __init__(self):
        self.queries = {}

    def collect(self, name, result):
        if name != "get_course_progress" or not result["ok"]:
            return
        key = f"P{len(self.queries) + 1}"
        self.queries[key] = CourseProgressArguments.model_validate(result["data"]["filters"])
        result["data"]["progress_query_id"] = key

    def answer(self, db, context, selection):
        keys = selection.get("query_ids")
        if not isinstance(keys, list) or not keys or len(keys) > 8 or any(
                not isinstance(key, str) or key not in self.queries for key in keys):
            raise ValueError("未读取的课程进度")
        db.expire_all()
        lines = []
        for key in dict.fromkeys(keys):
            args = self.queries[key]
            data = get_course_progress(db, context, args)
            cards, missing = data["review_cards"], data["missing_summaries"]
            lines.extend([f"{data['course_name']} · 课程进度",
                f"共 {data['lesson_total']} 节课；有文字记录 {data['transcript_lessons']} 节，可用纪要 {data['summary_lessons']} 节。",
                f"知识点共 {cards['total']} 个：未学习 {cards['new']} 个、需要复习 {cards['review']} 个、已掌握 {cards['mastered']} 个。状态由你手动标记。",
                f"缺少可用纪要的课次：{missing['total']} 节。"])
            for row in missing["items"]:
                lines.append(f"• {row['title']} · {SUMMARY_STATES.get(row['summary_status'], '暂不可用')}" +
                             (f" · {row['lesson_date']}" if row["lesson_date"] else ""))
            if missing["total"] and not missing["items"]:
                lines.append("当前分页没有记录。")
            elif missing["items"] and (args.offset or missing["next_offset"] is not None):
                lines.append(f"本次显示第 {args.offset + 1}–{args.offset + len(missing['items'])} 节，可继续分页查询。")
        return "\n\n".join(lines)

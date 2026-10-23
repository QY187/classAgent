"""业务查询由服务提供，最终回答重新核对记录。"""
from ..courses.pending import list_pending_lessons
from .schemas import PendingLessonsArguments, UnansweredQuizArguments, ProcessingDetailArguments
from ..lessons.processing import get_processing_detail
from .tools import check_lesson
from .learning import learning_scope
from ..quizzes.unanswered import list_unanswered
from .tools import check_course


def pending_lessons(db, context, args):
    course_id = args.course_id or context.course_id
    if course_id:
        check_course(db, context, course_id)
    result = list_pending_lessons(db, context.username, args.offset, args.limit,
                                  course_id=course_id, lesson_id=context.lesson_id)
    return result | {"filters": args.model_dump() | {"course_id": course_id}}


def unanswered_quizzes(db, context, args):
    course_id, lesson_id = learning_scope(db, context, args)
    return list_unanswered(db, context.username, course_id=course_id, lesson_id=lesson_id,
        query=args.query, offset=args.offset, limit=args.limit) | {
        "filters": args.model_dump() | {"course_id":course_id, "lesson_id":lesson_id}}


def processing_detail(db, context, args):
    check_lesson(db, context, args.lesson_id)
    return get_processing_detail(db, args.lesson_id, context.username) | {"filters":args.model_dump()}


READERS = {"get_processing_detail": (ProcessingDetailArguments, processing_detail),
           "list_pending_lessons": (PendingLessonsArguments, pending_lessons),
           "list_unanswered_quizzes": (UnansweredQuizArguments, unanswered_quizzes)}


class WorkflowQueryStore:
    def __init__(self):
        self.queries = {}

    def collect(self, name, result):
        if name not in READERS or not result["ok"]:
            return
        key = f"W{len(self.queries) + 1}"
        self.queries[key] = (name, READERS[name][0].model_validate(result["data"]["filters"]))
        result["data"]["workflow_query_id"] = key

    def answer(self, db, context, selection):
        keys = selection.get("query_ids")
        if not isinstance(keys, list) or not keys or any(key not in self.queries for key in keys):
            raise ValueError("未读取的业务记录")
        db.expire_all()
        lines = []
        for key in dict.fromkeys(keys):
            name, args = self.queries[key]
            data = READERS[name][1](db, context, args)
            if name == "get_processing_detail":
                lines.append(f"{data['course_name']} / [{data['title']}]({data['href']}) · {data['stage_label']}")
                job = data["transcription_job"]
                if job:
                    stages = {"queued":"排队中", "transcribing":"转写中", "completed":"已完成", "failed":"失败"}
                    label = stages.get(job["stage"], "处理中")
                    if job["stage"] == "failed" and data["lesson_status"] == "completed":
                        label += "（历史任务，当前文字已完成）"
                    lines.append(f"最近转写任务：{label} · 进度 {job['progress']}%。任务进度不代表纪要进度。")
                else:
                    lines.append("暂无转写处理任务。")
                labels = {"missing":"尚无纪要", "queued":"等待生成", "generating":"生成中",
                          "failed":"生成失败", "stale":"待更新", "completed":"已生成", "edited":"已编辑"}
                label = labels.get(data['summary_status'], '暂不可用')
                if data['summary_status'] in {"completed", "edited"} and not data["summary_available"]:
                    label = "内容为空，尚无可用纪要"
                lines.append(f"纪要状态：{label}。")
                if data['error_message']:
                    lines.append(f"当前失败原因：{data['error_message']}")
                continue
            if name == "list_unanswered_quizzes":
                lines.append(f"尚未提交作答的小测：共 {data['total']} 组。")
                for row in data["items"]:
                    lines.append(f"• {row['course_name']} / [{row['title']}]({row['href']}) · {row['question_count']} 道题")
                if not data["total"]:
                    lines.append("当前范围没有可答且尚未提交的小测。")
                elif not data["items"]:
                    lines.append("当前分页没有记录。")
                if data["has_more"]:
                    lines.append("还有更多小测，可继续分页查询。")
                continue
            lines.append(f"待处理课次：共 {data['total']} 节。")
            for row in data["items"]:
                lines.append(f"• {row['course_name']} / [{row['title']}]({row['href']}) · {row['stage_label']}" +
                             (f"\n失败原因：{row['error_message']}" if row['error_message'] else ""))
            if not data["total"]:
                lines.append("当前范围没有待处理课次。")
            elif not data["items"]:
                lines.append("当前分页没有记录。")
            if data["has_more"]:
                lines.append(f"本页 {len(data['items'])} 节，可从第 {args.offset + len(data['items']) + 1} 节继续查询。")
        return "\n\n".join(lines)

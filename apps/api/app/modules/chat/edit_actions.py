"""课程与课次信息修改，只接受本条指令明确指定的字段。"""
import re
from datetime import date
from fastapi import HTTPException
from ...shared.schemas import CourseUpdate, LessonUpdate
from ..courses import service as courses
from .access import owned_course, owned_lesson
from .intents import explicit_request, request_text, clarification_origin
from .course_actions import clean_name
from .action_records import perform_for_message


def edit_request(question):
    value = request_text(question).rstrip("。！! ")
    if not explicit_request(question) or re.search(r"别|不|取消|假如|假设|如果|示例|举例|教我|解释", value):
        return None
    value = re.sub(r"^(?:请|帮我|给我|麻烦你|麻烦|然后|再|\s)+", "", value)
    match = re.fullmatch(r"(?:把|将)(.+?)(?:的)?(?:改名为|重命名为|改名成)([^，,；;\n]+)(?:[，,；;]\s*日期(?:改为|改成|设为)([^，,；;\n]+))?", value)
    if match:
        target, name, day = match.groups()
        kind = "course" if target.endswith("课程") else "lesson"
        fields = {"name" if kind == "course" else "title":name.strip().strip('“”「」"\' ')}
        if day:
            fields["lesson_date"] = day.strip()
    else:
        match = re.fullmatch(r"(?:把|将)(.+?)(?:的)?(日期|学期)(?:改为|改成|设为)([^，,；;\n]+)", value)
        if not match:
            return None
        target, field, new = match.groups()
        kind = "course" if field == "学期" else "lesson"
        fields = {"semester" if field == "学期" else "lesson_date":new.strip().strip('“”「」"\' ')}
    target = clean_name(target)
    if kind == "course":
        target = target.removesuffix("课程")
    else:
        target = target.removesuffix("课次")
    return {"kind":kind, "target":target, "fields":fields}


def resolve_edit_request(question, history=None):
    direct = edit_request(question)
    if direct:
        return direct
    previous = clarification_origin(question, history)
    origin = edit_request(previous) if previous else None
    year = re.fullmatch(r"(\d{4})年?[。！! ]*", question.strip())
    if not origin or not year:
        return None
    partial = origin["fields"].get("lesson_date", "")
    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})日?", partial)
    if not month_day:
        return None
    try:
        day = date(int(year[1]), int(month_day[1]), int(month_day[2])).isoformat()
    except ValueError:
        return None
    return origin | {"fields":origin["fields"] | {"lesson_date":day}}


def action_hint(question, history=None, semantic=None):
    if semantic is not None:
        return semantic.get("edit", {})
    return resolve_edit_request(question, history) or {}


def actions_for_message(db, conversation_id, username, message_id, token, question, history=None, semantic=None):
    request = semantic.get("edit") if semantic is not None else resolve_edit_request(question, history)
    if not request:
        return {}
    tool = "update_course" if request["kind"] == "course" else "update_lesson"
    def change(args):
        values = args.model_dump(exclude_none=True)
        fields = request["fields"]
        identity = args.course_id if tool == "update_course" else args.lesson_id
        def validate(db, conversation, message, previous):
            if message.content != question:
                raise HTTPException(409, "修改指令已变化")
            actual = {key:value for key,value in values.items() if key not in {"course_id", "lesson_id"}}
            if actual != fields:
                raise HTTPException(400, "只修改本条指令明确指定的字段；日期需要完整的 YYYY-MM-DD")
            if "lesson_date" in fields:
                try:
                    if date.fromisoformat(fields["lesson_date"]).isoformat() != fields["lesson_date"]:
                        raise ValueError()
                except ValueError:
                    raise HTTPException(400, "请明确完整日期 YYYY-MM-DD，不猜测年份")
            if tool == "update_course":
                item = owned_course(db, identity, username, lock=True)
                if conversation.course_id and conversation.course_id != item.id:
                    raise HTTPException(404, "课程不存在")
                if not previous:
                    matches = [row for row in courses.list_courses(db, username) if row.name == request["target"]]
                    if len(matches) != 1 or matches[0].id != item.id:
                        raise HTTPException(400, "请明确唯一的目标课程名称")
                if "name" in fields and any(row.id != item.id and row.name.casefold() == fields["name"].casefold() for row in courses.list_courses(db, username)):
                    raise HTTPException(409, "已有同名课程，请使用其他名称")
            else:
                item = owned_lesson(db, identity, username, lock=True)
                course = owned_course(db, item.course_id, username)
                if conversation.course_id and conversation.course_id != course.id:
                    raise HTTPException(404, "课次不存在")
                if conversation.lesson_id and conversation.lesson_id != item.id:
                    raise HTTPException(404, "课次不存在")
                if not previous:
                    target = request["target"]
                    if not conversation.course_id:
                        prefix = course.name + "课程的"
                        if not target.startswith(prefix):
                            raise HTTPException(400, "请明确课程名称与课次标题，或进入对应课程对话")
                        target = target[len(prefix):]
                    matches = [row for row in courses.list_lessons(db, course.id, username) if row.title == target]
                    if len(matches) != 1 or matches[0].id != item.id:
                        raise HTTPException(400, "请明确唯一的目标课次标题")
                if "title" in fields and any(row.id != item.id and row.title.casefold() == fields["title"].casefold() for row in courses.list_lessons(db, course.id, username)):
                    raise HTTPException(409, "课程内已有同名课次，请使用其他标题")
        def write(db):
            if tool == "update_course":
                item = owned_course(db, identity, username, lock=True)
                old = {"name":item.name, "semester":item.semester}
                item = courses.update_course(db, item.id, CourseUpdate(name=fields.get("name",item.name), semester=fields.get("semester",item.semester)), username, commit=False)
                title, course_id = item.name, item.id
            else:
                item = owned_lesson(db, identity, username, lock=True)
                old = {"title":item.title, "lesson_date":item.lesson_date}
                item = courses.update_lesson(db, item.id, LessonUpdate(title=fields.get("title",item.title), lesson_date=fields.get("lesson_date",item.lesson_date)), username, commit=False)
                title, course_id = item.title, item.course_id
            labels = {"name":"课程名称", "semester":"学期", "title":"课次标题", "lesson_date":"日期"}
            changes = "；".join(f"{labels[key]}：{old[key] or '未设置'} → {value}" for key,value in fields.items())
            return {"kind":"action", "operation":tool, "target":request["kind"], "id":item.id,
                    "course_id":course_id, "title":title, "changes":fields,
                    "message":f"已修改{('课程' if tool == 'update_course' else '课次')}“{title}”：{changes}。"}
        return perform_for_message(db, conversation_id, username, message_id, token, tool, values, write, validate)
    return {tool:change}


def visible_action(db, result, username):
    try:
        if result["target"] == "course":
            owned_course(db, result["id"], username)
        else:
            item = owned_lesson(db, result["id"], username)
            if item.course_id != result["course_id"]:
                return None
        return result
    except HTTPException:
        return None

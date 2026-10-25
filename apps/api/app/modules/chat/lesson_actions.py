"""添加课次的指令解析与业务接入；不改变既有页面的课次排序规则。"""
import re
from fastapi import HTTPException
from sqlalchemy import select
from ...shared.models import AgentAction
from ...shared.schemas import LessonCreate
from ..courses import service as courses
from .action_records import perform_for_message
from .access import owned_course, owned_lesson
from .course_actions import explicit_request, clean_name, requested_course, resolve_course_request
from .intents import follows_clarification, request_text, clarification_origin


PREFIX = r"(?:请|帮我|给我|麻烦你|麻烦|然后|再|我想要|我想|你|\s)*"


def resolve_lesson_request(question, history):
    if lesson_request(question)[0]:
        return question
    course_request = resolve_course_request(question, history)
    if course_request != question and lesson_request(course_request)[0]:
        return course_request
    if follows_clarification(question, history) and question.strip() and not re.search(r"什么|为什么|解释|查询|看看|生成|修改|标记", question):
        previous = clarification_origin(question, history)
        if previous is None:
            return question
        previous_requested, previous_title = lesson_request(previous)
        if previous_requested and not previous_title:
            supplement = question.strip().rstrip("？?。！!").strip()
            prefix = re.split(r"添加|新增|创建|新建", previous, maxsplit=1)[0]
            day = re.search(r"(?:日期|时间)(?:为|是|[：:])?\s*(\d{4}-\d{2}-\d{2})", previous)
            suffix = f"，日期为{day[1]}" if day else ""
            return f"{prefix}添加课次：{supplement}{suffix}"
    return question


def action_hint(question, history=None):
    authorization = resolve_lesson_request(question, history)
    requested, title = lesson_request(authorization)
    match = re.search(r"(?:日期|时间)(?:为|是|[：:])?\s*(\d{4}-\d{2}-\d{2})", authorization)
    return {"title": title, "lesson_date": match[1] if match else None,
            "instruction": "标题已明确时不要再次询问；未指定日期时留空。先查询确定目标课程，然后执行添加。"} if requested else {}


def lesson_request(question):
    question = request_text(question)
    for clause in re.split(r"[，,。；;\n]", question):
        if not explicit_request(clause):
            continue
        match = re.match(r"^" + PREFIX + r"(?:(?:在|给|为).{1,200}?(?:课程|课)(?:下|中|里|的)?(?:\s|再)*)?(?:添加|新增|创建|新建)(.*)$", clause.strip())
        if not match:
            continue
        value = clean_name(re.sub(r"^一[个节]", "", match[1]))
        if "课程" in value:
            continue
        if value.startswith("课次"):
            title = re.sub(r"^课次(?:标题为|名为|叫|[：:])?", "", value)
            return True, clean_name(title) or None
        if value.endswith("课次"):
            return True, clean_name(value[:-2]) or None
        if re.fullmatch(r"第[一二三四五六七八九十百零\d]+讲", value):
            return True, value
    return False, None


def named_courses(db, username, question):
    return [row for row in courses.list_courses(db, username) if row.name + "课程" in question or
            re.search(r"(?:在|给|为)\s*[“\"]?" + re.escape(row.name) + r"[”\"]?(?:下|中|里|的)?(?:添加|新增|创建|新建)", question)]


def actions_for_message(db, conversation_id, username, message_id, token, question, history=None):
    raw_question = question
    question = resolve_lesson_request(question, history)
    requested, title = lesson_request(question)
    if not requested:
        return {}
    def create(args):
        def validate(db, conversation, message, previous):
            if message.content != raw_question or not title or args.title != title:
                raise HTTPException(400, "请明确要添加的课次标题，不猜测或改写标题")
            if conversation.lesson_id:
                raise HTTPException(403, "请在课程对话或主对话添加课次")
            if conversation.course_id:
                if args.course_id != conversation.course_id:
                    raise HTTPException(404, "课程不存在")
                named = re.search(r"(?:在|给|为)\s*(.{1,200}?)课程", question)
                if named and clean_name(named[1]) != owned_course(db, conversation.course_id, username).name:
                    raise HTTPException(400, "当前对话绑定其他课程，请进入目标课程对话或主对话")
            else:
                candidates = named_courses(db, username, question)
                if len(candidates) != 1 or candidates[0].id != args.course_id:
                    raise HTTPException(400, "请明确唯一的目标课程，或进入对应课程对话添加课次")
            course = owned_course(db, args.course_id, username, lock=True)
            if requested_course(question):
                import json
                created = db.scalar(select(AgentAction).where(AgentAction.message_id == message_id, AgentAction.tool == "create_course"))
                if created is None or json.loads(created.result_json)["id"] != course.id:
                    raise HTTPException(400, "请先成功创建本条指令指定的课程，再添加课次")
            date_match = re.search(r"(?:日期|时间)(?:为|是|[：:])?\s*(\d{4}-\d{2}-\d{2})", question)
            expected_date = date_match[1] if date_match else None
            if args.lesson_date != expected_date or (re.search(r"日期|时间", question) and not date_match):
                raise HTTPException(400, "日期需由你明确指定为 YYYY-MM-DD；未指定时保持为空")
            if previous:
                lesson = owned_lesson(db, previous["id"], username)
                if lesson.course_id != course.id:
                    raise HTTPException(409, "原创建课次已调整归属，不能重复创建")
            elif any(row.title.casefold() == title.casefold() for row in courses.list_lessons(db, course.id, username)):
                raise HTTPException(409, "这门课程已有同名课次，请确认已有课次或使用其他标题")
        def write(db):
            item = courses.create_lesson(db, args.course_id, LessonCreate(title=title, lesson_date=args.lesson_date), username, commit=False)
            course = owned_course(db, item.course_id, username)
            return {"kind": "action", "operation": "create_lesson", "target": "lesson", "id": item.id,
                    "title": item.title, "course_id": item.course_id,
                    "message": f"已在课程“{course.name}”添加课次：{item.title}。"}
        return perform_for_message(db, conversation_id, username, message_id, token, "create_lesson", args.model_dump(), write, validate)
    return {"create_lesson": create}


def visible_action(db, result, username):
    try:
        lesson = owned_lesson(db, result["id"], username)
        return result if lesson.course_id == result["course_id"] else None
    except HTTPException:
        return None

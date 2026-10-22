"""用户明确的课程创建指令；不会从课堂资料或历史生成写入授权。"""
import re
from fastapi import HTTPException
from sqlalchemy import select
from ...shared.models import Course
from ...shared.schemas import CourseCreate
from ..courses import service as courses
from .action_records import perform_for_message
from .access import owned_course
from .intents import explicit_request, follows_clarification, request_text


def clean_name(value):
    return value.strip().strip('“”「」\"\' ').removesuffix("的").strip()


def course_name(question):
    if not explicit_request(question):
        return None
    question = request_text(question)
    match = re.search(r"(?:创建|新建|添加|新增)(?:一[个门])?(?:名为|名字叫|叫|名称为)?([^，,。；;\n]{0,210}?)课程", question)
    if match:
        return clean_name(match[1]) or None
    match = re.search(r"(?:创建|新建|添加|新增)课程(?:[：:]|名为|叫)([^，,。；;\n]{1,200})", question)
    return clean_name(match[1]) if match else None


def requested_course(question):
    question = request_text(question)
    return explicit_request(question) and bool(re.match(r"^(?:请|帮我|给我|麻烦你|麻烦|然后|再|我想要|我想|我希望|你|一下|\s|[，,、])*(?:创建|新建|添加|新增)[^，,。；;\n]{0,210}?课程(?=$|[，,。；;\n]|再|然后)", question))


def action_hint(question, history=None):
    authorization = resolve_course_request(question, history)
    return {"name": course_name(authorization),
        "instruction": "当前用户已明确要求创建；名称给定时按指定名称执行，不因礼貌问尾再次确认。名称未给定时先询问。"}


def resolve_course_request(question, history):
    if requested_course(question):
        return question
    if follows_clarification(question, history) and explicit_request(question) and not re.search(r"什么|为什么|解释|查询|看看|生成|创建|添加|修改|标记", question):
        previous = next((item["content"] for item in reversed(history) if item.get("role") == "user"), "")
        previous_is_create = requested_course(previous) or (
            bool(re.match(r"^(?:请|帮我|给我|麻烦你|麻烦|我想要|我希望|你|一下|\s)*(?:创建|新建|添加|新增)课程", previous))
            and not re.search(r"不要|不需要|不用|取消|别|原文|老师说|引用", previous)
        )
        if previous_is_create and not course_name(previous):
            supplement = clean_name(question).rstrip("？?。！!").strip()
            return f"创建{supplement.removesuffix('课程')}课程"
    return question


def actions_for_message(db, conversation_id, username, message_id, token, question, history=None):
    actions = {}
    authorization = resolve_course_request(question, history)
    if requested_course(authorization):
        def create(args):
            name = course_name(authorization)
            def validate(db, conversation, message, previous):
                if conversation.course_id or conversation.lesson_id:
                    raise HTTPException(403, "请在主对话创建新课程")
                if message.content != question:
                    raise HTTPException(409, "操作指令已变化，请重新发送")
                if not name or args.name not in {name, name + "课程"}:
                    raise HTTPException(400, "请明确要创建的课程名称，不猜测或改写名称")
                if previous:
                    owned_course(db, previous["id"], username)
                elif any(row.name.casefold() == name.casefold() for row in courses.list_courses(db, username)):
                    raise HTTPException(409, "已有同名课程，请选择已有课程，或明确使用其他课程名称")
            def write(db):
                item = courses.create_course(db, CourseCreate(name=name), username, commit=False)
                return {"kind": "action", "operation": "create_course", "target": "course", "id": item.id,
                        "title": item.name, "course_id": item.id, "message": f"已创建课程：{item.name}。"}
            return perform_for_message(db, conversation_id, username, message_id, token,
                "create_course", {"name": name}, write, validate)
        actions["create_course"] = create
    return actions


def visible_action(db, result, username):
    if result.get("operation") == "create_course":
        try:
            owned_course(db, result["id"], username)
            return result
        except HTTPException:
            return None
    return None

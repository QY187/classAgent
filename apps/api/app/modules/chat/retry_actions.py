"""只从本条明确重试指令授权；课堂与历史不授权写入。"""
import re
from fastapi import HTTPException
from ..lessons.retry import prepare_retry, dispatch_retry
from ..lessons.service import get_lesson
from ..courses.service import list_lessons
from .access import owned_course
from .intents import explicit_request, request_text
from .action_records import perform_for_message


def retry_requested(question):
    value = request_text(question)
    return explicit_request(question) and not re.search(r"别|不|取消|假如|假设|如果|示例|举例|教我|解释", value) and bool(
        re.match(r"^(?:请|帮我|给我|麻烦你|麻烦|再|然后|\s)*(?:重试|重新处理|重新转写).{0,200}(?:转写|课|讲)", value))


def validate_target(db, conversation, username, question, lesson_id):
    lesson = get_lesson(db, lesson_id, username)
    if conversation.course_id and lesson.course_id != conversation.course_id:
        raise HTTPException(404, "课次不存在")
    if conversation.lesson_id and lesson.id != conversation.lesson_id:
        raise HTTPException(404, "课次不存在")
    course = owned_course(db, lesson.course_id, username)
    if not conversation.course_id and not (course.name in question):
        raise HTTPException(400, "请明确目标课程与课次，或进入对应课程对话")
    candidates = [row for row in list_lessons(db, course.id, username) if row.title in question]
    if len(candidates) != 1 or candidates[0].id != lesson.id:
        raise HTTPException(400, "请明确唯一的课次标题，不依据历史猜测目标")
    return lesson


def actions_for_message(db, conversation_id, username, message_id, token, question, history=None):
    if not retry_requested(question):
        return {}
    def retry(args):
        def validate(db, conversation, message, previous):
            if message.content != question:
                raise HTTPException(409, "操作指令已变化")
            validate_target(db, conversation, username, question, args.lesson_id)
        result = perform_for_message(db, conversation_id, username, message_id, token,
            "retry_transcription", args.model_dump(), lambda db:prepare_retry(db, args.lesson_id, username), validate)
        try:
            dispatch_retry(db, result)
        except Exception:
            pass  # 已持久登记，beat 会补投递；不声称已经开始转写。
        return result
    return {"retry_transcription":retry}


def visible_action(db, result, username):
    try:
        lesson = get_lesson(db, result["id"], username)
        return result if lesson.course_id == result["course_id"] else None
    except HTTPException:
        return None

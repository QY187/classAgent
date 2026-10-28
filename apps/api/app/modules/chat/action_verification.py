"""只读取本对话真实回执并复核现状，不恢复历史写权限。"""
import json
from fastapi import HTTPException
from sqlalchemy import select
from ...core.visibility import visible_get
from ...shared.models import AgentAction, ChatMessage, Course, ReviewCard, ProcessingJob
from .access import owned_conversation, owned_course, owned_lesson


def verify_actions(db, conversation_id, username, message_id, intent):
    conversation = owned_conversation(db, conversation_id, username)
    current = db.get(ChatMessage, message_id)
    if current is None or current.conversation_id != conversation_id:
        raise HTTPException(404, "消息不存在")
    target = intent.get("target")
    receipts = db.execute(select(AgentAction, ChatMessage).join(ChatMessage, AgentAction.message_id == ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation_id, ChatMessage.position < current.position)
        .order_by(ChatMessage.position.desc(), AgentAction.created_at.desc()).limit(50)).all()
    chosen, position = [], None
    for receipt, message in receipts:
        result = json.loads(receipt.result_json)
        if target and target not in message.content and target not in result.get("title", ""):
            continue
        if position is not None and message.position != position:
            break
        position = message.position
        chosen.append((receipt, result))
    if not chosen:
        return "没有找到对应的成功操作回执，不能确认已完成；本次核对不会重新执行操作。"
    lines = ["以下是本对话最近有成功回执的相关操作及当前状态（不代表其他没有回执的请求已完成）："]
    for receipt, result in chosen:
        args = json.loads(receipt.arguments_json)
        try:
            if result["target"] == "course":
                item = visible_get(db, Course, result["id"])
                if item is None:
                    raise HTTPException(404, "课程不可见")
                owned_course(db, item.id, username)
                scope = conversation.course_id or (owned_lesson(db, conversation.lesson_id, username).course_id if conversation.lesson_id else None)
                if scope and item.id != scope:
                    raise HTTPException(404, "超出当前范围")
                expected = result.get("changes", {"name": result["title"], "semester": result.get("semester")})
            elif result["target"] == "lesson":
                item = owned_lesson(db, result["id"], username)
                if conversation.course_id and item.course_id != conversation.course_id or conversation.lesson_id and item.id != conversation.lesson_id:
                    raise HTTPException(404, "超出当前范围")
                if receipt.tool == "retry_transcription":
                    job = db.get(ProcessingJob, result["job_id"])
                    label = {"queued": "排队中", "transcribing": "转写中", "completed": "已完成", "failed": "失败"}.get(job.stage, "处理中") if job and job.lesson_id == item.id else "任务不可用"
                    lines.append(f"已登记“{item.title}”的转写重试；该任务当前状态：{label}。")
                    continue
                expected = result.get("changes", {"title": result["title"], "lesson_date": args.get("lesson_date")})
            else:
                item = visible_get(db, ReviewCard, result["id"])
                if item is None:
                    raise HTTPException(404, "知识点不可见")
                lesson = owned_lesson(db, item.lesson_id, username)
                if conversation.course_id and lesson.course_id != conversation.course_id or conversation.lesson_id and lesson.id != conversation.lesson_id:
                    raise HTTPException(404, "超出当前范围")
                expected = {"status": result["status"]}
            labels = {"name": "名称", "semester": "学期", "title": "标题", "lesson_date": "日期", "status": "状态"}
            statuses = {"new": "未学习", "review": "需要复习", "mastered": "已掌握"}
            details = []
            for key, value in expected.items():
                actual = getattr(item, key)
                show = statuses.get(actual, actual) if key == "status" else actual
                details.append(f"{labels[key]}当前为“{show or '未设置'}”" + ("，与回执一致" if actual == value else "，与当时回执不同"))
            lines.append(f"“{result['title']}”有成功操作回执；" + "；".join(details) + "。")
        except HTTPException:
            lines.append("相关操作有成功回执，但目标目前不可见或超出当前对话范围，无法核对现状。")
    return "\n".join(lines)

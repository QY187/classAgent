"""课程写工具薄适配；权限和事务由聊天动作执行器绑定。"""
from fastapi import HTTPException
from .actions import execute_action
from .tools import check_course


def create_course(db, context, args):
    if context.course_id or context.lesson_id:
        raise HTTPException(403, "请在主对话创建新课程")
    return execute_action(db, context, "create_course", args)


def create_lesson(db, context, args):
    check_course(db, context, args.course_id)
    if context.lesson_id:
        raise HTTPException(403, "请在课程对话或主对话添加课次")
    return execute_action(db, context, "create_lesson", args)

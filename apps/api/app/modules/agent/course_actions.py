"""课程写工具薄适配；权限和事务由聊天动作执行器绑定。"""
from fastapi import HTTPException
from .actions import execute_action


def create_course(db, context, args):
    if context.course_id or context.lesson_id:
        raise HTTPException(403, "请在主对话创建新课程")
    return execute_action(db, context, "create_course", args)

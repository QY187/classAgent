from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...core.visibility import visible_get
from ...shared.models import ChatConversation, Course, Lesson


def owned_course(db: Session, identity: str, username: str, lock=False):
    query = select(Course).where(Course.id == identity).execution_options(populate_existing=True)
    course = db.scalar(query.with_for_update() if lock else query)
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(404, "课程不存在")
    return course


def owned_lesson(db: Session, identity: str, username: str, lock=False):
    lesson = visible_get(db, Lesson, identity)
    if lesson is None:
        raise HTTPException(404, "课次不存在")
    query = select(Course).where(Course.id == lesson.course_id)
    course = db.scalar(query.with_for_update() if lock else query)
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(404, "课次不存在")
    lesson = db.scalar(select(Lesson).where(Lesson.id == identity).execution_options(populate_existing=True))
    if lesson is None:
        raise HTTPException(404, "课次不存在")
    return lesson


def owned_conversation(db: Session, identity: str, username: str, lock=False):
    conversation = visible_get(db, ChatConversation, identity)
    if conversation is None:
        raise HTTPException(404, "对话不存在")
    if conversation.lesson_id is not None:
        owned_lesson(db, conversation.lesson_id, username, lock)
    else:
        owned_course(db, conversation.course_id, username, lock)
    query = select(ChatConversation).where(ChatConversation.id == identity).execution_options(populate_existing=True)
    conversation = db.scalar(query.with_for_update() if lock else query)
    if conversation is None or conversation.user_id != user_id_for_username(db, username):
        raise HTTPException(404, "对话不存在")
    return conversation

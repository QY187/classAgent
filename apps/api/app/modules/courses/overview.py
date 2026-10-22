"""课程库首页统计；只聚合当前用户可见的数据，不记录或推断学习时长。"""
from datetime import timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...shared.models import ChatConversation, ChatMessage, Course, Lesson, Quiz, QuizAttempt, ReviewCard
from .pending import pending_condition


def get_overview(db: Session, username: str) -> dict:
    owner = user_id_for_username(db, username)
    pending = db.scalar(select(func.count(Lesson.id)).join(Course).where(
        Course.owner_id == owner, pending_condition(),
    )) or 0

    activities = []
    attempt = db.execute(select(QuizAttempt, Quiz, Course).join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .join(Course, Quiz.course_id == Course.id).where(QuizAttempt.user_id == owner, Course.owner_id == owner)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc()).limit(1)).first()
    if attempt:
        record, quiz, course = attempt
        activities.append((record.created_at, "quiz", quiz.title, course.name, f"/quiz-attempts/{record.id}"))
    card = db.execute(select(ReviewCard, Course).join(Lesson, ReviewCard.lesson_id == Lesson.id)
        .join(Course, Lesson.course_id == Course.id)
        .where(Course.owner_id == owner, ReviewCard.course_id == Course.id, ReviewCard.last_reviewed_at.is_not(None))
        .order_by(ReviewCard.last_reviewed_at.desc(), ReviewCard.id.desc()).limit(1)).first()
    if card:
        record, course = card
        activities.append((record.last_reviewed_at, "review", record.title, course.name, f"/lessons/{record.lesson_id}/review"))
    message = db.execute(select(ChatMessage, ChatConversation).join(ChatConversation)
        .where(ChatConversation.user_id == owner, ChatConversation.is_archived.is_(False),
               ChatMessage.role == "user", ChatMessage.status == "completed")
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(1)).first()
    if message:
        record, conversation = message
        activities.append((record.created_at, "chat", conversation.title, None, f"/chat?conversation={conversation.id}"))

    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    recent = None
    if activities:
        at, kind, title, course_name, href = max(activities, key=lambda item: utc(item[0]))
        recent = {"at": utc(at).isoformat(), "kind": kind, "title": title, "course_name": course_name, "href": href}
    return {"pending_lessons": pending, "recent_learning": recent}

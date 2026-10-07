from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...shared.models import ChatConversation, Course, Lesson
from .conversations import conversation_read


def search_conversations(db: Session, username: str, query: str) -> list[dict]:
    query = query.strip()[:200]
    if not query:
        return []
    owner = user_id_for_username(db, username)
    rows = db.execute(select(ChatConversation, Lesson.title, Course.name)
        .join(Lesson, ChatConversation.lesson_id == Lesson.id).join(Course, Lesson.course_id == Course.id)
        .where(ChatConversation.user_id == owner, Course.owner_id == owner,
            or_(ChatConversation.title.icontains(query, autoescape=True), Lesson.title.icontains(query, autoescape=True), Course.name.icontains(query, autoescape=True)))
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id).limit(100))
    return [{**conversation_read(item), "lesson_title": lesson_title, "course_name": course_name} for item, lesson_title, course_name in rows]

"""给语义规划提供有界、可见的实体名称，不把历史命令作为写入依据。"""
from sqlalchemy import select
from ...shared.models import Course, Lesson, ReviewCard


ENTITY_LIMIT = 30


def intent_entities(db, user_id, course_id=None, lesson_id=None):
    courses = select(Course).where(Course.owner_id == user_id)
    if course_id:
        courses = courses.where(Course.id == course_id)
    rows = list(db.scalars(courses.order_by(Course.created_at.desc(), Course.id).limit(ENTITY_LIMIT + 1)))
    result = {"courses": [row.name for row in rows[:ENTITY_LIMIT]], "courses_truncated": len(rows) > ENTITY_LIMIT}
    if not course_id:
        return result
    lessons = select(Lesson).join(Course).where(Course.owner_id == user_id, Lesson.course_id == course_id)
    cards = select(ReviewCard).join(Course, Course.id == ReviewCard.course_id).where(
        Course.owner_id == user_id, ReviewCard.course_id == course_id)
    if lesson_id:
        lessons = lessons.where(Lesson.id == lesson_id)
        cards = cards.where(ReviewCard.lesson_id == lesson_id)
    lesson_rows = list(db.scalars(lessons.order_by(Lesson.created_at.desc(), Lesson.id).limit(ENTITY_LIMIT + 1)))
    card_rows = list(db.scalars(cards.order_by(ReviewCard.created_at.desc(), ReviewCard.id).limit(ENTITY_LIMIT + 1)))
    result.update({"lessons": [row.title for row in lesson_rows[:ENTITY_LIMIT]],
                   "lessons_truncated": len(lesson_rows) > ENTITY_LIMIT,
                   "knowledge_points": [row.title for row in card_rows[:ENTITY_LIMIT]],
                   "knowledge_points_truncated": len(card_rows) > ENTITY_LIMIT})
    return result

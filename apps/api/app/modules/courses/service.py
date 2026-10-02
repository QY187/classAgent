from ...core.visibility import visible_get
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ..recycle_bin.service import move_to_bin
from ...shared.models import Course, Lesson, LessonSummary, Quiz, QuizAnswer, QuizAttempt, ReviewCard, TranscriptSegment
from ...shared.schemas import CourseCreate, CourseUpdate, LessonCreate, LessonUpdate
from . import mapper


def create_course(db: Session, payload: CourseCreate, owner_username: str) -> Course:
    return mapper.save_course(db, Course(owner_id=user_id_for_username(db, owner_username), owner_username=owner_username, name=payload.name, semester=payload.semester))


def list_courses(db: Session, owner_username: str) -> list[Course]:
    return mapper.find_courses(db, user_id_for_username(db, owner_username))


def get_course_progress(db: Session, course_id: str, owner_username: str) -> dict:
    course = mapper.find_course(db, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")

    lesson_total = db.scalar(select(func.count(Lesson.id)).where(Lesson.course_id == course_id)) or 0
    transcript_lessons = db.scalar(
        select(func.count(func.distinct(TranscriptSegment.lesson_id)))
        .join(Lesson, TranscriptSegment.lesson_id == Lesson.id)
        .where(Lesson.course_id == course_id)
    ) or 0
    summary_lessons = db.scalar(
        select(func.count(LessonSummary.id))
        .join(Lesson, LessonSummary.lesson_id == Lesson.id)
        .where(
            Lesson.course_id == course_id,
            LessonSummary.status.in_(("completed", "edited")),
            LessonSummary.content.is_not(None),
            LessonSummary.content != "",
        )
    ) or 0
    card_counts = {"new": 0, "review": 0, "mastered": 0}
    for status, count in db.execute(
        select(ReviewCard.status, func.count(ReviewCard.id))
        .where(ReviewCard.course_id == course_id)
        .group_by(ReviewCard.status)
    ):
        if status in card_counts:
            card_counts[status] = count
    attempt_count, average_score = db.execute(
        select(
            func.count(QuizAttempt.id),
            func.avg(100.0 * QuizAttempt.correct_count / func.nullif(QuizAttempt.total_count, 0)),
        ).join(Quiz, QuizAttempt.quiz_id == Quiz.id).where(
            Quiz.course_id == course_id, QuizAttempt.user_id == course.owner_id
        )
    ).one()
    recent = db.execute(
        select(QuizAttempt, Quiz.title)
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .where(Quiz.course_id == course_id, QuizAttempt.user_id == course.owner_id)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(1)
    ).first()
    wrong_question_count = db.scalar(
        select(func.count(func.distinct(QuizAnswer.question_id)))
        .join(QuizAttempt, QuizAnswer.attempt_id == QuizAttempt.id)
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .where(Quiz.course_id == course_id, QuizAttempt.user_id == course.owner_id, QuizAnswer.is_correct.is_(False))
    ) or 0
    return {
        "course_id": course_id,
        "lesson_total": lesson_total,
        "transcript_lessons": transcript_lessons,
        "summary_lessons": summary_lessons,
        "review_cards": {"total": sum(card_counts.values()), **card_counts},
        "quizzes": {
            "attempt_count": attempt_count,
            "average_score": round(average_score) if average_score is not None else None,
            "wrong_question_count": wrong_question_count,
            "recent_attempt": {
                "id": recent[0].id,
                "title": recent[1],
                "correct_count": recent[0].correct_count,
                "total_count": recent[0].total_count,
                "created_at": recent[0].created_at.isoformat(),
            } if recent else None,
        },
    }


def update_course(db: Session, course_id: str, payload: CourseUpdate, owner_username: str) -> Course:
    course = mapper.find_course(db, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="课程名称不能为空")
    course.name = name
    course.semester = payload.semester.strip() or None if payload.semester else None
    db.commit()
    db.refresh(course)
    return course


def create_lesson(db: Session, course_id: str, payload: LessonCreate, owner_username: str) -> Lesson:
    course = db.scalar(select(Course).where(Course.id == course_id).with_for_update())
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    first_order = db.scalar(select(func.min(Lesson.sort_order)).where(Lesson.course_id == course_id))
    return mapper.save_lesson(db, Lesson(course_id=course_id, title=payload.title, lesson_date=payload.lesson_date, sort_order=(first_order - 1) if first_order is not None else 0))


def reorder_lessons(db: Session, course_id: str, lesson_ids: list[str], expected_ids: list[str], owner_username: str) -> list[Lesson]:
    course = db.scalar(select(Course).where(Course.id == course_id).with_for_update())
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    lessons = mapper.find_lessons(db, course_id)
    current_ids = [lesson.id for lesson in lessons]
    if len(set(lesson_ids)) != len(lesson_ids):
        raise HTTPException(status_code=400, detail="课次不能重复")
    if current_ids != expected_ids or set(current_ids) != set(lesson_ids):
        raise HTTPException(status_code=409, detail="课次列表已发生变化，请刷新后重新排序")
    by_id = {lesson.id: lesson for lesson in lessons}
    for index, lesson_id in enumerate(lesson_ids):
        by_id[lesson_id].sort_order = index
    db.commit()
    return mapper.find_lessons(db, course_id)


def list_lessons(db: Session, course_id: str, owner_username: str) -> list[Lesson]:
    course = mapper.find_course(db, course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课程不存在")
    return mapper.find_lessons(db, course_id)


def update_lesson(db: Session, lesson_id: str, payload: LessonUpdate, owner_username: str) -> Lesson:
    lesson = visible_get(db, Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="课次不存在")
    course = mapper.find_course(db, lesson.course_id)
    if course is None or course.owner_id != user_id_for_username(db, owner_username):
        raise HTTPException(status_code=404, detail="课次不存在")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="课次标题不能为空")
    lesson.title = title
    lesson.lesson_date = payload.lesson_date or None
    db.commit()
    db.refresh(lesson)
    return lesson


def delete_lesson(db: Session, lesson_id: str, owner_username: str) -> None:
    move_to_bin(db, "lesson", lesson_id, owner_username)


def delete_course(db: Session, course_id: str, owner_username: str) -> None:
    move_to_bin(db, "course", course_id, owner_username)

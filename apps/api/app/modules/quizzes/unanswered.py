"""尚无本人提交作答的小测，提供列表信息，不读取答案。"""
from sqlalchemy import exists, func, select
from ...core.ownership import user_id_for_username
from ...shared.models import Course, Quiz, QuizAttempt, QuizQuestion


def list_unanswered(db, username, *, course_id=None, lesson_id=None, query="", offset=0, limit=20):
    owner = user_id_for_username(db, username)
    submitted = exists(select(QuizAttempt.id).where(QuizAttempt.quiz_id == Quiz.id,
                       QuizAttempt.user_id == owner).correlate(Quiz))
    conditions = [Course.owner_id == owner, Quiz.status == "ready", ~submitted]
    if course_id:
        conditions.append(Quiz.course_id == course_id)
    if lesson_id:
        # 多课次来源以业务服务的解析结果筛选，避免 JSON 字符串模糊匹配。
        from .service import _quiz_lesson_ids
    rows = db.execute(select(Quiz, Course).join(Course).where(*conditions)
                      .order_by(Quiz.created_at.desc(), Quiz.id.desc())).all()
    rows = [(quiz, course) for quiz, course in rows if query.casefold() in quiz.title.casefold()
            and (not lesson_id or lesson_id in _quiz_lesson_ids(quiz))]
    selected = rows[offset:offset + limit]
    counts = dict(db.execute(select(QuizQuestion.quiz_id, func.count(QuizQuestion.id))
                  .where(QuizQuestion.quiz_id.in_([quiz.id for quiz, _ in selected]))
                  .group_by(QuizQuestion.quiz_id)).all()) if selected else {}
    return {"total":len(rows), "items":[{"id":quiz.id, "course_id":course.id,
            "course_name":course.name, "title":quiz.title, "question_count":counts.get(quiz.id, 0),
            "href":f"/quizzes/{quiz.id}", "created_at":quiz.created_at.isoformat()}
            for quiz, course in selected], "has_more":offset + len(selected) < len(rows)}

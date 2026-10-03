"""统一隐藏回收站内容；维护操作显式使用 include_deleted，不向业务模块散布过滤条件。"""
from sqlalchemy import and_, event, exists, or_, select
from sqlalchemy.orm import Session, with_loader_criteria


def _criteria():
    from ..shared import models as m

    courses = m.Course.__table__.alias("visible_course")
    lessons = m.Lesson.__table__.alias("visible_lesson")
    quizzes = m.Quiz.__table__.alias("visible_quiz")
    questions = m.QuizQuestion.__table__.alias("visible_question")

    def course_active(column):
        return exists(select(courses.c.id).where(courses.c.id == column, courses.c.deleted_at.is_(None)).correlate_except(courses))

    def lesson_active(column):
        return exists(select(lessons.c.id).where(lessons.c.id == column, lessons.c.deleted_at.is_(None),
                                                course_active(lessons.c.course_id)).correlate_except(lessons))

    def quiz_active(column):
        return exists(select(quizzes.c.id).where(quizzes.c.id == column, course_active(quizzes.c.course_id),
                      or_(quizzes.c.lesson_id.is_(None), lesson_active(quizzes.c.lesson_id))).correlate_except(quizzes))

    rules = [(m.Course, m.Course.deleted_at.is_(None)),
             (m.Lesson, and_(m.Lesson.deleted_at.is_(None), course_active(m.Lesson.course_id))),
             (m.CourseMaterial, and_(m.CourseMaterial.deleted_at.is_(None), course_active(m.CourseMaterial.course_id),
                 or_(m.CourseMaterial.lesson_id.is_(None), lesson_active(m.CourseMaterial.lesson_id)))),
             (m.Quiz, and_(course_active(m.Quiz.course_id), or_(m.Quiz.lesson_id.is_(None), lesson_active(m.Quiz.lesson_id)))),
             (m.QuizQuestion, quiz_active(m.QuizQuestion.quiz_id)), (m.QuizAttempt, quiz_active(m.QuizAttempt.quiz_id))]
    for model in (m.AudioFile, m.ProcessingJob, m.TranscriptSegment, m.LessonSummary, m.SpeakerAlias, m.DocumentChunk, m.ReviewCard, m.ChatConversation):
        rules.append((model, lesson_active(model.lesson_id)))
    for model in (m.QuizAnswer, m.QuizQuestionRetry):
        rules.append((model, exists(select(questions.c.id).where(questions.c.id == model.question_id,
                     quiz_active(questions.c.quiz_id)).correlate_except(questions))))
    segments = m.TranscriptSegment.__table__.alias("visible_segment")
    conversations = m.ChatConversation.__table__.alias("visible_conversation")
    rules.append((m.ChatMessage, exists(select(conversations.c.id).where(
        conversations.c.id == m.ChatMessage.conversation_id, lesson_active(conversations.c.lesson_id)
    ).correlate_except(conversations))))
    rules.append((m.TranscriptRevision, exists(select(segments.c.id).where(segments.c.id == m.TranscriptRevision.segment_id,
                  lesson_active(segments.c.lesson_id)).correlate_except(segments))))
    return [with_loader_criteria(model, condition, include_aliases=True, propagate_to_loaders=False) for model, condition in rules]


@event.listens_for(Session, "do_orm_execute")
def hide_recycled_content(state):
    if state.is_select and not state.is_column_load and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(*_criteria())


def visible_get(db: Session, model, identity):
    """始终查询可见性，避免同一会话的身份缓存绕过过滤。"""
    return db.scalar(select(model).where(model.id == identity))

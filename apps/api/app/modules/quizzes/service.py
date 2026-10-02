import json

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.ownership import user_id_for_username
from ...shared.models import Course, Lesson, Quiz, QuizAnswer, QuizAttempt, QuizQuestion, ReviewCard, TranscriptSegment
from ..summaries.service import _parse_json
from .schemas import QuizGenerate, QuizQuestionUpdate, QuizSubmit


def _owned_course(db: Session, course_id: str, username: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def _owned_quiz(db: Session, quiz_id: str, username: str) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="小测不存在")
    _owned_course(db, quiz.course_id, username)
    return quiz


def _source_segments(db: Session, course_id: str, lesson_id: str | None) -> list[TranscriptSegment]:
    query = select(TranscriptSegment).join(Lesson, TranscriptSegment.lesson_id == Lesson.id).where(Lesson.course_id == course_id)
    if lesson_id:
        query = query.where(Lesson.id == lesson_id)
    rows = list(db.scalars(query.order_by(Lesson.created_at, TranscriptSegment.start_ms)).all())
    if len(rows) <= 60:
        return rows
    return [rows[round(i * (len(rows) - 1) / 59)] for i in range(60)]


def _generate_questions(segments: list[TranscriptSegment], count: int) -> list[dict]:
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status_code=503, detail="未配置 AI 服务，无法生成课堂小测")
    sources = "\n".join(f"[{i}] {segment.text[:350]}" for i, segment in enumerate(segments, 1))
    prompt = (
        f"只根据以下课堂文字记录出 {count} 道不重复的小测题，单选题和判断题均可。"
        "每题只有一个明确正确答案；不要引入课堂记录以外的事实，也不要为模糊内容出题。"
        "返回严格 JSON：{\"questions\":[{\"kind\":\"single_choice 或 true_false\",\"stem\":\"题干\","
        "\"options\":[\"选项1\",\"选项2\",\"选项3\",\"选项4\"],\"correct_option\":0,"
        "\"explanation\":\"为什么正确\",\"source_index\":1,\"evidence\":\"逐字摘录一小段原文\"}]}。"
        "判断题 options 必须是 [\"正确\",\"错误\"]；correct_option 是从 0 开始的选项下标。"
        "evidence 必须是所选 source_index 对应原文中的连续原字，不要改写。\n\n课堂记录：\n" + sources
    )
    try:
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={"model": settings.summary_model, "messages": [{"role": "system", "content": "你是谨慎的课堂出题员。只输出 JSON。"}, {"role": "user", "content": prompt}], "temperature": 0.1},
            timeout=120,
        )
        response.raise_for_status()
        payload = _parse_json(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="小测生成失败，请稍后重试") from exc
    items = payload.get("questions")
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="AI 未返回可用题目，请重试")
    valid = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        stem = str(item.get("stem") or "").strip()
        options = item.get("options")
        correct = item.get("correct_option")
        explanation = str(item.get("explanation") or "").strip()
        source_index = item.get("source_index")
        evidence = str(item.get("evidence") or "").strip()
        if (kind not in {"single_choice", "true_false"} or not stem or len(stem) > 500 or stem in seen
                or not isinstance(options, list) or len(options) != (2 if kind == "true_false" else 4)
                or any(not isinstance(option, str) or not option.strip() or len(option) > 200 for option in options)
                or len({option.strip() for option in options}) != len(options) or (kind == "true_false" and options != ["正确", "错误"])
                or type(correct) is not int or not 0 <= correct < len(options)
                or not explanation or len(explanation) > 2000
                or type(source_index) is not int or not 1 <= source_index <= len(segments)
                or len(evidence) < 4 or len(evidence) > 180 or evidence not in segments[source_index - 1].text):
            continue
        seen.add(stem)
        valid.append({"kind": kind, "stem": stem, "options": [option.strip() for option in options],
                      "correct_option": correct, "explanation": explanation, "source": segments[source_index - 1], "evidence": evidence})
        if len(valid) == count:
            break
    if len(valid) < 3:
        raise HTTPException(status_code=502, detail="生成的题目缺少可核对的课堂依据，请重试")
    return valid


def serialize_quiz(quiz: Quiz, reveal_answers: bool = False) -> dict:
    return {
        "id": quiz.id, "course_id": quiz.course_id, "lesson_id": quiz.lesson_id,
        "title": quiz.title, "status": quiz.status, "created_at": quiz.created_at,
        "questions": [{
            "id": q.id, "kind": q.kind, "stem": q.stem, "options": json.loads(q.options_json),
            "source_lesson_id": q.source_lesson_id, "source_start_ms": q.source_start_ms,
            "source_excerpt": q.source_excerpt,
            **({"correct_option": q.correct_option, "explanation": q.explanation} if reveal_answers else {}),
        } for q in quiz.questions],
    }


def generate_quiz(db: Session, course_id: str, payload: QuizGenerate, username: str) -> dict:
    course = _owned_course(db, course_id, username)
    lesson = db.get(Lesson, payload.lesson_id) if payload.lesson_id else None
    if payload.lesson_id and (lesson is None or lesson.course_id != course_id):
        raise HTTPException(status_code=400, detail="所选课次不属于当前课程")
    segments = [segment for segment in _source_segments(db, course_id, payload.lesson_id) if segment.text.strip()]
    if len(segments) < 3:
        raise HTTPException(status_code=400, detail="文字记录不足，至少需要 3 段内容才能生成小测")
    generated = _generate_questions(segments, payload.count)
    quiz = Quiz(course_id=course_id, lesson_id=payload.lesson_id,
                title=f"{lesson.title if lesson else course.name} · 课堂小测", status="draft")
    for position, item in enumerate(generated, 1):
        source = item["source"]
        quiz.questions.append(QuizQuestion(
            position=position, kind=item["kind"], stem=item["stem"], options_json=json.dumps(item["options"], ensure_ascii=False),
            correct_option=item["correct_option"], explanation=item["explanation"],
            source_segment_id=source.id, source_lesson_id=source.lesson_id,
            source_start_ms=source.start_ms, source_excerpt=item["evidence"],
        ))
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return serialize_quiz(quiz, reveal_answers=True)


def list_quizzes(db: Session, course_id: str, username: str) -> list[dict]:
    _owned_course(db, course_id, username)
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course_id).order_by(Quiz.created_at.desc())).all()
    return [{"id": quiz.id, "title": quiz.title, "lesson_id": quiz.lesson_id, "status": quiz.status,
             "question_count": len(quiz.questions), "created_at": quiz.created_at} for quiz in quizzes]


def get_quiz(db: Session, quiz_id: str, username: str) -> dict:
    quiz = _owned_quiz(db, quiz_id, username)
    return serialize_quiz(quiz, reveal_answers=quiz.status == "draft")


def update_question(db: Session, quiz_id: str, question_id: str, payload: QuizQuestionUpdate, username: str) -> dict:
    quiz = _owned_quiz(db, quiz_id, username)
    if quiz.status != "draft":
        raise HTTPException(status_code=409, detail="小测开始答题后不能修改题目")
    question = next((item for item in quiz.questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    options = [item.strip() for item in payload.options]
    if len(options) != (2 if question.kind == "true_false" else 4) or any(not item for item in options) or len(set(options)) != len(options):
        raise HTTPException(status_code=400, detail="选项数量或内容不正确")
    if question.kind == "true_false" and options != ["正确", "错误"]:
        raise HTTPException(status_code=400, detail="判断题的选项必须是正确、错误")
    if payload.correct_option >= len(options) or not payload.stem.strip() or not payload.explanation.strip():
        raise HTTPException(status_code=400, detail="请填写题目、解析和有效答案")
    question.stem = payload.stem.strip()
    question.options_json = json.dumps(options, ensure_ascii=False)
    question.correct_option = payload.correct_option
    question.explanation = payload.explanation.strip()
    db.commit()
    return serialize_quiz(quiz, reveal_answers=True)


def publish_quiz(db: Session, quiz_id: str, username: str) -> dict:
    quiz = _owned_quiz(db, quiz_id, username)
    if quiz.status != "draft":
        raise HTTPException(status_code=409, detail="小测已经开始答题")
    quiz.status = "ready"
    db.commit()
    return serialize_quiz(quiz)


def serialize_attempt(db: Session, attempt: QuizAttempt) -> dict:
    quiz = db.get(Quiz, attempt.quiz_id)
    selected = {answer.question_id: answer for answer in attempt.answers}
    return {
        "id": attempt.id, "quiz_id": attempt.quiz_id, "course_id": quiz.course_id,
        "title": quiz.title, "correct_count": attempt.correct_count,
        "total_count": attempt.total_count, "created_at": attempt.created_at,
        "questions": [{
            "id": q.id, "kind": q.kind, "stem": q.stem, "options": json.loads(q.options_json),
            "selected_option": selected[q.id].selected_option,
            "correct_option": q.correct_option, "is_correct": selected[q.id].is_correct,
            "explanation": q.explanation, "source_segment_id": q.source_segment_id,
            "source_lesson_id": q.source_lesson_id, "source_start_ms": q.source_start_ms,
            "source_excerpt": q.source_excerpt,
        } for q in quiz.questions],
    }


def submit_quiz(db: Session, quiz_id: str, payload: QuizSubmit, username: str) -> dict:
    quiz = _owned_quiz(db, quiz_id, username)
    if quiz.status != "ready":
        raise HTTPException(status_code=409, detail="请先核对并开始小测")
    questions = quiz.questions
    if set(payload.answers) != {question.id for question in questions}:
        raise HTTPException(status_code=400, detail="请回答全部题目后提交")
    for question in questions:
        selected = payload.answers[question.id]
        if type(selected) is not int or not 0 <= selected < len(json.loads(question.options_json)):
            raise HTTPException(status_code=400, detail="答案选项无效")
    user_id = user_id_for_username(db, username)
    attempt = QuizAttempt(quiz_id=quiz_id, user_id=user_id,
                          correct_count=sum(payload.answers[q.id] == q.correct_option for q in questions),
                          total_count=len(questions))
    attempt.answers = [QuizAnswer(question_id=q.id, selected_option=payload.answers[q.id],
                                  is_correct=payload.answers[q.id] == q.correct_option) for q in questions]
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return serialize_attempt(db, attempt)


def list_attempts(db: Session, quiz_id: str, username: str) -> list[dict]:
    _owned_quiz(db, quiz_id, username)
    user_id = user_id_for_username(db, username)
    attempts = db.scalars(select(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id, QuizAttempt.user_id == user_id)
                          .order_by(QuizAttempt.created_at.desc())).all()
    return [{"id": attempt.id, "correct_count": attempt.correct_count, "total_count": attempt.total_count,
             "created_at": attempt.created_at} for attempt in attempts]


def get_attempt(db: Session, attempt_id: str, username: str) -> dict:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != user_id_for_username(db, username):
        raise HTTPException(status_code=404, detail="答题记录不存在")
    _owned_quiz(db, attempt.quiz_id, username)
    return serialize_attempt(db, attempt)


def add_wrong_answer_to_review(db: Session, attempt_id: str, question_id: str, username: str) -> dict:
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != user_id_for_username(db, username):
        raise HTTPException(status_code=404, detail="答题记录不存在")
    quiz = _owned_quiz(db, attempt.quiz_id, username)
    answer = db.scalar(select(QuizAnswer).where(QuizAnswer.attempt_id == attempt_id, QuizAnswer.question_id == question_id))
    question = db.get(QuizQuestion, question_id)
    if answer is None or question is None or answer.is_correct or question.quiz_id != quiz.id:
        raise HTTPException(status_code=400, detail="只能将本次答错的题目加入知识点")
    if not question.source_lesson_id or not question.source_segment_id:
        raise HTTPException(status_code=409, detail="原课堂片段已不存在，无法建立有来源的卡片")
    origin_key = f"quiz:{question.id}"
    existing = db.scalar(select(ReviewCard).where(ReviewCard.lesson_id == question.source_lesson_id,
                                                  ReviewCard.origin_key == origin_key))
    if existing:
        return {"card_id": existing.id, "created": False}
    options = json.loads(question.options_json)
    card = ReviewCard(
        course_id=quiz.course_id, lesson_id=question.source_lesson_id, card_type="question",
        title=question.stem[:200],
        body=f"正确答案：{options[question.correct_option]}\n解析：{question.explanation}"[:10000],
        status="review", origin_key=origin_key,
        source_segment_id=question.source_segment_id,
        source_start_ms=question.source_start_ms, source_excerpt=question.source_excerpt,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return {"card_id": card.id, "created": True}

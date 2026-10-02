from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from . import service
from .schemas import QuizGenerate, QuizQuestionUpdate, QuizSubmit


router = APIRouter(tags=["quizzes"])


@router.post("/courses/{course_id}/quizzes", status_code=201)
def generate_quiz(course_id: str, payload: QuizGenerate, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.generate_quiz(db, course_id, payload, username)


@router.get("/courses/{course_id}/quizzes")
def list_quizzes(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_quizzes(db, course_id, username)


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_quiz(db, quiz_id, username)


@router.patch("/quizzes/{quiz_id}/questions/{question_id}")
def update_question(quiz_id: str, question_id: str, payload: QuizQuestionUpdate,
                    username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.update_question(db, quiz_id, question_id, payload, username)


@router.post("/quizzes/{quiz_id}/publish")
def publish_quiz(quiz_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.publish_quiz(db, quiz_id, username)


@router.post("/quizzes/{quiz_id}/attempts", status_code=201)
def submit_quiz(quiz_id: str, payload: QuizSubmit, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.submit_quiz(db, quiz_id, payload, username)


@router.get("/quizzes/{quiz_id}/attempts")
def list_attempts(quiz_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_attempts(db, quiz_id, username)


@router.get("/quiz-attempts/{attempt_id}")
def get_attempt(attempt_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_attempt(db, attempt_id, username)


@router.post("/quiz-attempts/{attempt_id}/questions/{question_id}/review-card")
def add_wrong_answer_to_review(attempt_id: str, question_id: str,
                               username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.add_wrong_answer_to_review(db, attempt_id, question_id, username)

"""对话小测动作：授权、幂等和生成后的安全结果。"""
import re
import json
from fastapi import HTTPException
from sqlalchemy import select
from ...shared.models import Quiz, Course
from ..quizzes.schemas import QuizGenerate
from ..quizzes.service import generate_quiz
from ..agent.schemas import PracticeQuizArguments
from ..quizzes.practice import PracticeSelection
from .intents import quiz_request


def wants_quiz(question, history=None):
    if re.search(r"(不要|别|不需要|不用).{0,12}(生成|出题|小测|题)", question):
        return False
    if re.search(r"(怎么|如何|是否|能不能|能否|可以.*吗)", question) and not re.search(r"(请|帮我|给我)", question):
        return False
    if quiz_request(question):
        return True
    # 用户补充上一条生成请求的范围时沿用授权；普通追问不能开启写工具。
    if history and len(question) <= 80 and re.search(r"(课程|讲|课|道|选择|判断|单选|混合)", question) and not re.search(r"(什么|为什么|如何|怎么|解释|取消)", question):
        if history[-1].get("role") == "assistant" and history[-1].get("content", "").rstrip().endswith(("？", "?")):
            previous = next((item for item in reversed(history) if item.get("role") == "user"), None)
            return bool(previous and wants_quiz(previous.get("content", "")))
    return False


def wants_practice_quiz(question, history=None):
    if not wants_quiz(question, history):
        return False
    if re.search(r"(薄弱|错题|待巩固|需要复习|没掌握|未掌握)", question):
        return True
    # 只在回答范围澄清时继承练习方式，普通新出题请求不沿用历史方式。
    if not wants_quiz(question) and history:
        previous = next((item for item in reversed(history) if item.get("role") == "user"), None)
        return bool(previous and wants_practice_quiz(previous.get("content", "")))
    return False


def quiz_card(db, quiz):
    course = db.get(Course, quiz.course_id)
    return {"kind": "quiz", "id": quiz.id, "course_id": quiz.course_id, "title": quiz.title,
            "course_name": course.name, "question_count": len(quiz.questions), "lesson_ids": json.loads(quiz.lesson_ids_json) if quiz.lesson_ids_json else ([quiz.lesson_id] if quiz.lesson_id else [])}


def generate_for_message(db, conversation_id, username, question_id, token, args):
    from .access import owned_conversation
    from .generation import GenerationStopped
    def before_save():
        db.rollback()
        conversation = owned_conversation(db, conversation_id, username, lock=True)
        if conversation.generation_token != token:
            raise GenerationStopped()
        if conversation.course_id is not None and args.course_id != conversation.course_id:
            raise HTTPException(404, "课程不存在或当前对话不可访问")
    before_save()
    db.commit()  # 不在模型生成期间持有对话锁。
    practice = isinstance(args, PracticeQuizArguments)
    selection = PracticeSelection(tuple(args.knowledge_point_ids), tuple(args.wrong_question_ids)) if practice else None
    result = generate_quiz(db, args.course_id, QuizGenerate(lesson_ids=None if practice else args.lesson_ids, count=args.count,
        question_type=args.question_type), username, agent_request_key=question_id, before_save=before_save, practice=selection)
    quiz = db.scalar(select(Quiz).where(Quiz.id == result["id"]))
    return quiz_card(db, quiz)

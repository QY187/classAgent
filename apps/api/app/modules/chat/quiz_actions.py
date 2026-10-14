"""对话小测动作：授权、幂等和生成后的安全结果。"""
import re
import json
from sqlalchemy import select
from ...shared.models import Quiz, Course
from ..quizzes.schemas import QuizGenerate
from ..quizzes.service import generate_quiz


def wants_quiz(question, history=None):
    if re.search(r"(不要|别|不需要|不用).{0,12}(生成|出题|小测|题)", question):
        return False
    if re.search(r"(怎么|如何|是否|能不能|能否|可以.*吗)", question) and not re.search(r"(请|帮我|给我)", question):
        return False
    if re.search(r"(生成|出|创建|做|来|给).{0,30}(小测|测试|题)|(小测|测试|题).{0,20}(生成|出|创建)", question):
        return True
    # 用户补充上一条生成请求的范围时沿用授权；普通追问不能开启写工具。
    if history and len(question) <= 80 and re.search(r"(课程|讲|课|道|选择|判断|单选|混合)", question) and not re.search(r"(什么|为什么|如何|怎么|解释|取消)", question):
        if history[-1].get("role") == "assistant" and history[-1].get("content", "").rstrip().endswith(("？", "?")):
            previous = next((item for item in reversed(history) if item.get("role") == "user"), None)
            return bool(previous and wants_quiz(previous.get("content", "")))
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
    before_save()
    db.commit()  # 不在模型生成期间持有对话锁。
    result = generate_quiz(db, args.course_id, QuizGenerate(lesson_ids=args.lesson_ids, count=args.count,
        question_type=args.question_type), username, agent_request_key=question_id, before_save=before_save)
    quiz = db.scalar(select(Quiz).where(Quiz.id == result["id"]))
    return quiz_card(db, quiz)

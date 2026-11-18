from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.db import Base
from app.shared.models import User, Course, Lesson, CourseMaterial, MaterialChunk, MaterialProcessing, Quiz, QuizQuestion
from app.modules.quizzes.schemas import QuizGenerate, QuizSubmit, WrongQuestionRetry
from app.modules.quizzes.service import generate_quiz, submit_quiz, retry_wrong_question, list_wrong_questions
from app.modules.quizzes.material_sources import material_sources
from app.modules.quizzes.migrations import prepare_quiz_scope
from app.modules.agent.tools import generate_quiz as agent_generate, ToolContext
from app.modules.agent.schemas import QuizArguments


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id="u", username="owner", password_hash="x"), User(id="other", username="other", password_hash="x")]); db.flush()
        db.add_all([Course(id="c", owner_id="u", name="课程"), Course(id="foreign", owner_id="other", name="他人课程")]); db.flush()
        db.add(Lesson(id="l", course_id="c", title="第一讲")); db.flush()
        for identity, course, lesson in [("m", "c", "l"), ("public", "c", None), ("foreign", "foreign", None)]:
            db.add(CourseMaterial(id=identity, course_id=course, lesson_id=lesson, filename=identity+".pdf", content_type="application/pdf", object_key=identity, size_bytes=10)); db.flush()
            db.add(MaterialProcessing(material_id=identity, status="ready", active_version="v1"))
            db.add(MaterialChunk(id=identity+"-chunk", material_id=identity, version="v1", position=0, locator_type="page", locator_number=2, content="二叉树每个节点最多有两个孩子。", embedding=[0.0]*1536))
        db.add(MaterialChunk(id="stale", material_id="m", version="old", position=1, locator_type="page", locator_number=3, content="过期版本原文", embedding=[0.0]*1536))
        db.commit()
        yield db
    engine.dispose()


def generated(sources, count, kind):
    return [dict(kind="true_false", stem=f"判断{i}", options=["正确", "错误"], correct_option=0,
                 explanation="原文定义", source=sources[0], evidence="最多有两个孩子") for i in range(3)]


def test_material_generation_results_and_wrong_retry_keep_locator(db):
    with patch("app.modules.quizzes.service._generate_questions", side_effect=generated):
        quiz = generate_quiz(db, "c", QuizGenerate(source_type="material", material_ids=["m"]), "owner")
    assert all(set(q) == {"id", "kind", "stem", "options"} for q in quiz["questions"])
    result = submit_quiz(db, quiz["id"], QuizSubmit(answers={q["id"]: 1 for q in quiz["questions"]}), "owner")
    source = result["questions"][0]["source_material"]
    assert (source["filename"], source["locator_number"], source["source_status"]) == ("m.pdf", 2, "current")
    assert source["chunk_id"] == "m-chunk"
    assert result["questions"][0]["source_segment_id"] is None
    wrong = list_wrong_questions(db, "owner")[0]
    assert "source_material" not in wrong  # 答题前不泄露引用原文
    retry = retry_wrong_question(db, wrong["id"], WrongQuestionRetry(selected_option=0), "owner")
    assert retry["source_material"]["source_status"] == "current"
    db.get(MaterialProcessing, "m").active_version = "v2"; db.commit()
    retry = retry_wrong_question(db, wrong["id"], WrongQuestionRetry(selected_option=0), "owner")
    assert retry["source_material"]["source_status"] == "changed"


@pytest.mark.parametrize("change", ["replace", "delete", "lesson"])
def test_changed_sources_prevent_save(db, change):
    def mutate():
        if change == "replace": db.get(MaterialProcessing, "m").active_version = "v2"
        elif change == "delete": db.get(CourseMaterial, "m").deleted_at = datetime.now(timezone.utc)
        else: db.get(Lesson, "l").deleted_at = datetime.now(timezone.utc)
        db.commit()
    with patch("app.modules.quizzes.service._generate_questions", side_effect=generated), pytest.raises(HTTPException):
        generate_quiz(db, "c", QuizGenerate(source_type="material", material_ids=["m"]), "owner", before_save=mutate)
    assert not list(db.scalars(select(Quiz)))


def test_material_scope_active_version_and_permissions(db):
    assert {s.id for s in material_sources(db,"c",["l"],None,"owner")} == {"m-chunk"}
    for identities, lessons in [(["foreign"],None), (["missing"],None), (["public"],["l"])]:
        with pytest.raises(HTTPException): material_sources(db,"c",lessons,identities,"owner")
    with pytest.raises(HTTPException): generate_quiz(db,"c",QuizGenerate(source_type="material"),"other")
    db.get(MaterialProcessing,"m").active_version=None; db.commit()
    with pytest.raises(HTTPException): material_sources(db,"c",None,["m"],"owner")


def test_agent_material_preference_selects_material_backend(db):
    calls=[]
    context=ToolContext(username="owner", course_id="c", generate_quiz=lambda args: calls.append(args) or {}, action_hints={"source_type":"material"})
    agent_generate(db, context, QuizArguments(course_id="c", material_ids=["m"]))
    assert calls[0].source_type == "material"


def test_old_question_table_migration_is_repeatable():
    engine=create_engine("sqlite:///:memory:")
    with engine.begin() as conn: conn.execute(text("CREATE TABLE quiz_questions (id TEXT PRIMARY KEY)"))
    prepare_quiz_scope(engine); prepare_quiz_scope(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO quiz_questions (id) VALUES ('old')"))
        assert conn.execute(text("SELECT source_material_json FROM quiz_questions")).scalar() is None
    engine.dispose()


def test_material_pipeline_generates_and_independently_reviews_before_saving(db):
    import json
    sources = material_sources(db, "c", None, ["m"], "owner")
    candidates = {"questions": [dict(kind="true_false", stem=f"第{i}条二叉树定义成立", options=["正确", "错误"],
                    correct_option=0, explanation="原文明确给出最多两个孩子", source_index=1, evidence="最多有两个孩子") for i in range(3)]}
    reviews = {"reviews": [dict(id=i, supported=True, unique=True, explanation_supported=True, answer=0) for i in range(3)]}
    def reply(body):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"choices":[{"message":{"content":json.dumps(body)}}]})
    settings=SimpleNamespace(deepseek_api_key="test", summary_model="test")
    with patch("app.modules.quizzes.service.get_settings", return_value=settings), patch("app.modules.quizzes.review.get_settings", return_value=settings), patch("app.modules.quizzes.service.httpx.post", side_effect=[reply(candidates), reply(reviews)]) as model:
        result=generate_quiz(db,"c",QuizGenerate(source_type="material", material_ids=["m"], count=3, question_type="true_false"),"owner")
    assert len(result["questions"]) == 3
    assert model.call_count == 2
    assert "二叉树每个节点" in model.call_args_list[0].kwargs["json"]["messages"][1]["content"]


def test_agent_message_honors_file_names_and_reuses_question_key(db):
    from app.modules.chat.conversations import create_global_conversation
    from app.modules.chat.quiz_actions import generate_for_message
    from app.shared.models import ChatConversation
    chat=create_global_conversation(db,"owner")
    conversation=db.get(ChatConversation,chat["id"])
    conversation.generation_token="token"; db.commit()
    args=QuizArguments(course_id="c",source_type="material",material_ids=["m"],count=3,question_type="true_false")
    with patch("app.modules.quizzes.service._generate_questions",side_effect=generated) as generator:
        card=generate_for_message(db,chat["id"],"owner","request","token",args,requested={"source_type":"material","materials":["m.pdf"]})
        repeated=generate_for_message(db,chat["id"],"owner","request","token",args,requested={"source_type":"material","materials":["m.pdf"]})
        assert card["id"] == repeated["id"]
        assert generator.call_count == 1
        with pytest.raises(HTTPException):
            generate_for_message(db,chat["id"],"owner","new-request","token",args,requested={"materials":["public.pdf"]})


def test_agent_ambiguous_filename_requires_clarification_before_generation(db):
    from app.modules.chat.conversations import create_global_conversation
    from app.modules.chat.quiz_actions import generate_for_message
    from app.shared.models import ChatConversation
    db.get(CourseMaterial,"public").filename="m.pdf"; db.commit()
    chat=create_global_conversation(db,"owner")
    db.get(ChatConversation,chat["id"]).generation_token="token"; db.commit()
    args=QuizArguments(course_id="c",source_type="material",material_ids=["m"],count=3)
    with patch("app.modules.quizzes.service._generate_questions") as generator, pytest.raises(HTTPException) as error:
        generate_for_message(db,chat["id"],"owner","request","token",args,requested={"materials":["m.pdf"]})
    assert "同名歧义" in error.value.detail
    generator.assert_not_called()


def test_agent_submitted_result_uses_material_citations(db):
    from app.modules.agent.quiz_results import get_quiz_attempt, QuizResultStore
    from app.modules.agent.schemas import QuizAttemptArguments
    with patch("app.modules.quizzes.service._generate_questions",side_effect=generated):
        quiz=generate_quiz(db,"c",QuizGenerate(source_type="material",material_ids=["m"]),"owner")
    attempt=submit_quiz(db,quiz["id"],QuizSubmit(answers={q["id"]:1 for q in quiz["questions"]}),"owner")
    context=ToolContext(username="owner",course_id="c")
    result=get_quiz_attempt(db,context,QuizAttemptArguments(attempt_id=attempt["id"]))
    store=QuizResultStore(); store.collect("get_quiz_attempt",{"ok":True,"data":result})
    answer=store.answer(db,context,{"query_ids":["Q1"]})
    assert answer["citations"][0]["source_type"] == "material"
    assert answer["citations"][0]["locator_number"] == 2
    assert "课件来源" in answer["answer"]
    assert "课堂来源当前不可用" not in answer["answer"]

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from app.modules.quizzes.review import review_questions
from app.modules.quizzes.service import _generate_questions


def question():
    return dict(kind="true_false", stem="二叉树每个节点最多两个孩子。", options=["正确", "错误"],
                correct_option=0, explanation="原文定义", evidence="最多两个孩子",
                source=SimpleNamespace(text="二叉树每个节点最多两个孩子。"))


def test_review_rejects_disagreement_ambiguity_missing_and_duplicate_decisions():
    good = dict(supported=True, unique=True, explanation_supported=True, answer=0)
    rows = [dict(good, id=0), dict(good, id=1, answer=1), dict(good, id=2, unique=False),
            dict(good, id=3, supported="true"), dict(good, id=4, explanation_supported=False),
            dict(good, id=5), dict(good, id=5), dict(good, id=6, answer=True)]
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        "choices": [{"message": {"content": json.dumps({"reviews": rows})}}]})
    questions = [question() for _ in range(8)]
    with patch("app.modules.quizzes.review.get_settings", return_value=SimpleNamespace(deepseek_api_key="test", summary_model="test")), patch("app.modules.quizzes.review.quota_chat_post", return_value=response) as call:
        assert review_questions(questions) == [questions[0]]
        assert call.call_args.kwargs["purpose"] == "quiz_review"


@pytest.mark.parametrize("response", [None, {"reviews": "invalid"}, {"reviews": []}])
def test_invalid_or_empty_review_never_passes_questions(response):
    reply = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        "choices": [{"message": {"content": json.dumps(response)}}]})
    with patch("app.modules.quizzes.review.get_settings", return_value=SimpleNamespace(deepseek_api_key="test", summary_model="test")), patch("app.modules.quizzes.review.quota_chat_post", return_value=reply):
        if response and response["reviews"] == []:
            assert review_questions([question()]) == []
        else:
            with pytest.raises(HTTPException):
                review_questions([question()])


def test_rejected_questions_trigger_bounded_refill_and_failure():
    source = SimpleNamespace(id="s", lesson_id="l", text="有效的课堂原文")
    with patch("app.modules.quizzes.service._request_questions", return_value=[]) as request:
        with pytest.raises(HTTPException):
            _generate_questions([source], 5)
        assert request.call_count == 3

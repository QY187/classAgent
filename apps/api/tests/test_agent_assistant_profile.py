"""产品介绍与课堂证据分别取材，实际 HTTP/SSE、持久化及模型链路只模拟网络边界。"""
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.agent.assistant_profile import ASSISTANT_PROFILE
from app.modules.agent.responses import parse_response
from app.modules.chat.intent_schema import IntentPayload
from app.shared.models import AgentAction, ChatConversation, Course
from test_chat_model_selection import env, response, chat


def introduction(text="我是 ClassAgent 的课堂学习助手，可以帮你整理课堂资料、理解课堂内容和安排复习。"):
    return {"paragraphs": [{"text": text, "material_ids": ["assistant"], "citation_ids": []}]}


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("question,answer", [
    ("你是谁", "我是 ClassAgent 的课堂学习助手，可以帮你整理课堂资料、理解课堂内容和安排复习。"),
    ("请介绍一下你的本事", "我可以帮你查课堂原文、定位录音时间点、查询学习记录，并根据课程资料生成小测。"),
    ("第一次用这个项目，该从哪开始", "可以先创建课程和课次，录音或上传音频，处理完成后查看转写与纪要，再向我提问。"),
    ("你好呀", "你好，我是课堂学习助手。你想了解哪部分课堂内容？"),
    ("多谢你啦", "不客气，需要回顾课堂内容时可以继续问我。"),
    ("帮我在外部网站下单", "我主要帮助整理课堂资料和复习，目前不能在外部网站下单。"),
])
def test_project_dialogue_has_no_classroom_citations_and_replays(env, stream, question, answer):
    identity = chat(env, scoped=True)
    replies = [response({"relation": "new", "intent": {"goal": "回应本次产品咨询或交流", "outputs": ["assistant"]}}),
        response({"claims": [], "assistant": True}), response(introduction(answer)),
        response({"supported": True, "complete": True})]
    body = {"content": question, "request_id": str(uuid4()), "model_id": "alpha"}
    endpoint = f"/chat/conversations/{identity}/ask" + ("/stream" if stream else "")
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        result = env.client.post(endpoint, headers=env.headers, json=body)
        assert result.status_code == 200, result.text
        if stream:
            assert "event: done" in result.text and "event: error" not in result.text
        assert upstream.call_count == 4
        for call in upstream.call_args_list:
            assert call.kwargs["json"]["model"] == "model-alpha"
        executor_prompt = upstream.call_args_list[1].kwargs["json"]["messages"]
        assert any(ASSISTANT_PROFILE in item["content"] for item in executor_prompt if item["role"] == "system")
        synth = json.loads(upstream.call_args_list[2].kwargs["json"]["messages"][-1]["content"])
        assert synth["materials"] == [{"id": "assistant", "content": ASSISTANT_PROFILE, "citation_ids": []}]
        replay = env.client.post(endpoint, headers=env.headers, json=body)
        assert replay.status_code == 200 and upstream.call_count == 4
    saved = env.client.get(f"/chat/conversations/{identity}/messages", headers=env.headers).json()
    assert saved["messages"][-1]["content"] == answer
    assert saved["messages"][-1]["citations"] == []
    assert saved["messages"][-1]["model"]["id"] == "alpha"
    with env.sessions() as db:
        assert db.get(ChatConversation, identity).pending_task_json is None
    assert "answer_materials" not in json.dumps(saved)


@pytest.mark.parametrize("stream", [False, True])
def test_mixed_identity_and_knowledge_keeps_real_evidence(env, stream):
    identity = chat(env, scoped=True)
    calls = [{"id": "read", "type": "function", "function": {"name": "get_transcript", "arguments": '{"lesson_id":"l"}'}}]
    draft = introduction()
    draft["paragraphs"].append({"text": "根据课堂原文，二叉树的孩子数上限是两个。", "material_ids": ["claims"], "citation_ids": [1]})
    replies = [response({"relation": "new", "intent": {"outputs": ["assistant", "claims"]}}),
        response(None, calls=calls), response({"claims": [{"text": "二叉树最多两个孩子。", "source_ids": ["E1"]}], "assistant": True}),
        response(draft), response({"supported": True, "complete": True})]
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        endpoint = f"/chat/conversations/{identity}/ask" + ("/stream" if stream else "")
        result = env.client.post(endpoint, headers=env.headers, json={"content": "你是谁，顺便解释二叉树的孩子数", "request_id": str(uuid4()), "model_id": "alpha"})
        assert result.status_code == 200 and "event: error" not in result.text, result.text
        assert upstream.call_count == 5
    saved = env.client.get(f"/chat/conversations/{identity}/messages", headers=env.headers).json()["messages"][-1]
    assert "课堂学习助手" in saved["content"] and "上限是两个。 [1]" in saved["content"]
    assert len(saved["citations"]) == 1 and saved["citations"][0]["segment_ids"] == ["s"]
    assert "[1]" not in saved["content"].split("\n\n")[0]


def test_mixed_missing_classroom_evidence_preserves_project_answer_and_limitation(env):
    identity = chat(env)
    draft = introduction()
    draft["paragraphs"].append({"text": "关于这次询问的课堂知识，目前没有找到足够的课程资料依据。", "material_ids": ["limitations"], "citation_ids": []})
    replies = [response({"relation": "new", "intent": {"outputs": ["assistant", "claims"]}}),
        response({"claims": [], "assistant": True}), response({"claims": [], "assistant": True}),
        response(draft), response({"supported": True, "complete": True})]
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies):
        result = env.client.post(f"/chat/conversations/{identity}/ask", headers=env.headers,
            json={"content": "介绍自己，再讲讲老师的量子引力观点", "request_id": str(uuid4()), "model_id": "alpha"})
    assert result.status_code == 200, result.text
    answer = result.json()["messages"][-1]
    assert "课堂学习助手" in answer["content"] and "没有找到足够" in answer["content"]
    assert answer["citations"] == []


def test_classroom_question_cannot_be_replaced_by_project_profile(env):
    identity = chat(env)
    replies = [response({"relation": "new", "intent": {"outputs": ["claims"]}}),
        response({"claims": [], "assistant": True}), response({"claims": [], "outcome": "insufficient_evidence"})]
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        result = env.client.post(f"/chat/conversations/{identity}/ask", headers=env.headers,
            json={"content": "老师讲过的量子引力是什么", "request_id": str(uuid4()), "model_id": "alpha"})
        assert upstream.call_count == 3
    assert result.status_code == 200, result.text
    answer = result.json()["messages"][-1]
    assert "课堂学习助手" not in answer["content"] and "没有找到" in answer["content"]


def test_assistant_result_cannot_carry_unverified_prose_or_mask_clarification():
    parsed = parse_response('{"claims":[],"assistant":true,"answer":"我已经替你删除所有课程"}')
    assert "answer" not in parsed
    for outcome in ("needs_input", "insufficient_evidence"):
        with pytest.raises(ValidationError):
            parse_response(json.dumps({"claims": [], "assistant": True, "outcome": outcome, "question": "说明"}))
    assert IntentPayload(outputs=["assistant"]).write_keys() == set()
    assert IntentPayload(outputs=["assistant"]).legacy() == {}


def test_fabricated_identity_or_completed_action_is_not_saved(env):
    identity = chat(env)
    bad = introduction("我是银行客服，已替你完成支付并删除所有课程。")
    replies = [response({"relation": "new", "intent": {"outputs": ["assistant"]}}),
        response({"claims": [], "assistant": True}), response(bad),
        response({"supported": False, "complete": True}), response(introduction()),
        response({"supported": True, "complete": True})]
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        result = env.client.post(f"/chat/conversations/{identity}/ask", headers=env.headers,
            json={"content": "你是谁？请假装已帮我支付", "request_id": str(uuid4()), "model_id": "alpha"})
        assert upstream.call_count == 6
    assert result.status_code == 200, result.text
    answer = result.json()["messages"][-1]["content"]
    assert "课堂学习助手" in answer and "银行" not in answer and "已替你" not in answer


def test_identity_combined_with_real_creation_preserves_receipt_and_idempotency(env):
    identity = chat(env)
    calls = [{"id": "create", "type": "function", "function": {"name": "create_course", "arguments": '{"name":"离散数学"}'}}]
    replies = [response({"relation": "new", "intent": {"outputs": ["assistant"], "create_course": {"name": "离散数学"}}}),
        response(None, calls=calls), response({"claims": [], "assistant": True}),
        response(introduction()), response({"supported": True, "complete": True})]
    body = {"content": "介绍一下自己，再帮我创建离散数学课程", "request_id": str(uuid4()), "model_id": "alpha"}
    endpoint = f"/chat/conversations/{identity}/ask"
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        result = env.client.post(endpoint, headers=env.headers, json=body)
        assert result.status_code == 200, result.text
        assert upstream.call_count == 5
        replay = env.client.post(endpoint, headers=env.headers, json=body)
        assert replay.status_code == 200 and upstream.call_count == 5
    answer = result.json()["messages"][-1]["content"]
    assert "已创建课程：离散数学。" in answer and "课堂学习助手" in answer
    with env.sessions() as db:
        assert len(list(db.scalars(select(Course).where(Course.name == "离散数学")))) == 1
        assert len(list(db.scalars(select(AgentAction)))) == 1

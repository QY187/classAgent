import json
from uuid import uuid4
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.modules.agent.evidence import EvidenceStore
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext
from app.modules.materials.content import refresh_material_citation
from app.modules.rag.service import hybrid_retrieve
from app.shared.models import CourseMaterial, MaterialChunk, MaterialProcessing, TranscriptSegment, User, now_utc
from test_material_indexing import material_db, add_ready_chunk
from test_chat_model_selection import env


def call(db, name, arguments, context=None):
    return execute_tool(db, context or ToolContext("owner", "c"), name, arguments)


def test_material_tools_scope_paging_and_source_restrictions(material_db):
    db = material_db
    add_ready_chunk(db)
    result = call(db, "list_materials", {"course_id": "c", "query": "讲义"})
    assert result["ok"] and result["data"]["items"][0]["indexed"]
    result = call(db, "get_material_content", {"course_id": "c", "material_id": "m", "locator_number": 3})
    assert result["ok"] and result["data"]["items"][0]["locator_label"] == "第 3 页"
    assert call(db, "get_material_content", {"course_id": "c", "material_id": "m", "locator_number": 2})["data"]["items"] == []
    restricted = ToolContext("owner", "c", action_hints={"source_type": "transcript"})
    assert not call(db, "get_material_content", {"course_id": "c", "material_id": "m"}, restricted)["ok"]
    restricted = ToolContext("owner", "c", action_hints={"source_type": "material"})
    assert not call(db, "get_transcript", {"lesson_id": "l"}, restricted)["ok"]
    db.get(CourseMaterial, "m").lesson_id = None
    db.commit()
    lesson_context = ToolContext("owner", "c", "l")
    assert call(db, "list_materials", {"course_id": "c"}, lesson_context)["data"]["items"] == []
    assert not call(db, "get_material_content", {"course_id": "c", "material_id": "m"}, lesson_context)["ok"]


def test_evidence_cannot_forge_or_reuse_changed_material(material_db):
    db = material_db
    add_ready_chunk(db)
    context = ToolContext("owner", "c")
    store = EvidenceStore()
    result = call(db, "get_material_content", {"course_id": "c", "material_id": "m"})
    store.collect(db, context, "get_material_content", result)
    row = result["data"]["items"][0]
    assert row["evidence_id"] == "E1"
    answer = store.answer(db, context, [{"text": row["text"], "source_ids": ["E1"]}])
    citation = answer["citations"][0]
    assert citation["source_type"] == "material" and citation["start_ms"] is None
    assert citation["locator_number"] == 3 and "课件依据" in answer["answer"]
    assert refresh_material_citation(db, citation, "owner")["source_status"] == "current"
    location = store.location_answer(db, context, {"source_ids": ["E1"]})
    assert "讲义.txt" in location["answer"] and "第 3 页" in location["answer"]
    db.get(MaterialProcessing, "m").active_version = "next"
    db.commit()
    assert store.answer(db, context, [{"text": row["text"], "source_ids": ["E1"]}])["citations"] == []
    assert refresh_material_citation(db, citation, "owner")["source_status"] == "changed"
    db.get(CourseMaterial, "m").deleted_at = now_utc()
    db.commit()
    assert refresh_material_citation(db, citation, "owner")["source_status"] == "unavailable"


def test_truncated_content_and_forged_versions_never_gain_evidence(material_db):
    db = material_db
    add_ready_chunk(db)
    context = ToolContext("owner", "c")
    result = call(db, "get_material_content", {"course_id": "c", "material_id": "m"})
    result["data"]["items"][0]["text"] = "不存在的秘密内容"
    store = EvidenceStore()
    store.collect(db, context, "get_material_content", result)
    assert not store.entries
    result["data"]["items"][0]["version"] = "old"
    store.collect(db, context, "get_material_content", result)
    assert not store.entries


def test_mixed_hybrid_retrieval_works_without_vector_service(material_db):
    db = material_db
    add_ready_chunk(db)
    with patch("app.modules.rag.service._rewrite_query", side_effect=lambda text: text), \
         patch("app.modules.rag.service.embed_texts", side_effect=RuntimeError("unavailable")), \
         patch("app.modules.rag.service._cross_encoder_rerank", return_value=None):
        rows = hybrid_retrieve(db, "c", "owner", "二叉树", source_type="all")
        assert [row.id for row in rows] == ["chunk"]
        result = call(db, "search_course", {"course_id": "c", "query": "二叉树"})
        assert result["ok"] and result["data"]["items"][0]["source_type"] == "material"
        restricted = ToolContext("owner", "c", action_hints={"source_type": "transcript"})
        assert call(db, "search_course", {"course_id": "c", "query": "二叉树", "source_type": "material"}, restricted)["data"]["items"] == []
        db.get(CourseMaterial, "m").deleted_at = now_utc()
        db.commit()
        assert hybrid_retrieve(db, "c", "owner", "二叉树", source_type="material") == []


def model_call(name, arguments, identity):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": identity, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def test_material_only_course_can_answer_without_transcript(material_db):
    db = material_db
    add_ready_chunk(db)
    db.get(CourseMaterial, "m").lesson_id = None
    db.commit()
    context = ToolContext("owner", "c", action_hints={"source_type": "material", "response_contract": {
        "goal": "解释课件的二叉树", "outputs": ["claims"], "requirements": []}})
    responses = [model_call("list_materials", {"course_id": "c"}, "files"),
        model_call("get_material_content", {"course_id": "c", "material_id": "m"}, "read"),
        {"role": "assistant", "content": json.dumps({"claims": [{"text": "二叉树每个结点最多有两个孩子。", "source_ids": ["E1"]}]})}]
    with patch("app.modules.agent.loop.complete", side_effect=responses):
        result = run_agent(db, context, "课件中二叉树的特点是什么")
    assert result["outcome"] == "answered"
    assert result["citations"][0]["lesson_id"] is None
    assert result["citations"][0]["filename"] == "讲义.txt"


@pytest.mark.parametrize("stream", [False, True])
def test_material_chat_http_sse_history_and_idempotence(env, stream):
    from test_chat_model_selection import response, chat
    from app.modules.chat.messages import read_messages
    with env.sessions() as db:
        db.add(CourseMaterial(id="m", course_id="c", lesson_id="l", filename="讲义.pdf", content_type="application/pdf", object_key="materials/m.pdf", size_bytes=20))
        db.commit()
        add_ready_chunk(db)
    identity = chat(env, scoped=True)
    replies = [response({"relation": "new", "intent": {"outputs": ["claims"], "source_type": "material"}}),
        response(None, calls=[{"id": "read", "type": "function", "function": {"name": "get_material_content", "arguments": '{"course_id":"c","material_id":"m"}'}}]),
        response({"claims": [{"text": "二叉树每个结点最多有两个孩子。", "source_ids": ["E1"]}]}),
        response({"paragraphs": [{"text": "课件说明二叉树每个结点最多有两个孩子。", "material_ids": ["claims"], "citation_ids": [1]}]}),
        response({"supported": True, "complete": True})]
    endpoint = f"/chat/conversations/{identity}/ask" + ("/stream" if stream else "")
    body = {"content": "只看课件解释二叉树", "request_id": str(uuid4()), "model_id": "alpha"}
    with patch("app.modules.agent.completion.httpx.post", side_effect=replies) as upstream:
        result = env.client.post(endpoint, headers=env.headers, json=body)
        assert result.status_code == 200, result.text
        assert "event: error" not in result.text
        assert upstream.call_count == 5
        result = env.client.post(endpoint, headers=env.headers, json=body)
        assert upstream.call_count == 5
    with env.sessions() as db:
        saved = read_messages(db, identity, "owner")
        assert saved["messages"][-1]["citations"][0]["source_type"] == "material"
        assert saved["messages"][0]["steps"][0]["label"] == "读取课件原文"
        db.get(CourseMaterial, "m").deleted_at = now_utc()
        db.commit()
        assert read_messages(db, identity, "owner")["messages"][-1]["citations"][0]["source_status"] == "unavailable"


def test_material_catalog_uses_actual_read_ids_and_current_state(material_db):
    db = material_db
    add_ready_chunk(db)
    context = ToolContext("owner", "c", action_hints={"semantic_queries": ["catalog"],
        "semantic_catalog": ["list_materials"], "response_contract": {"outputs": ["catalog"], "requirements": []}})
    store = EvidenceStore()
    assert store.catalog_answer(db, context, {"material_ids": ["m"]}) == []
    result = call(db, "list_materials", {"course_id": "c"})
    store.collect(db, context, "list_materials", result, {"course_id": "c"})
    assert store.catalog_complete({"list_materials"})
    assert "讲义.txt" in store.catalog_answer(db, context, {"material_ids": ["m"]})[0]
    db.get(CourseMaterial, "m").deleted_at = now_utc()
    db.commit()
    assert store.catalog_answer(db, context, {"material_ids": ["m"]}) == []


def test_material_catalog_agent_returns_verified_file_without_content_claims(material_db):
    db = material_db
    add_ready_chunk(db)
    context = ToolContext("owner", "c", action_hints={"semantic_queries": ["catalog"],
        "semantic_catalog": ["list_materials"], "response_contract": {"outputs": ["catalog"], "requirements": []}})
    responses = [model_call("list_materials", {"course_id": "c"}, "files"),
        {"role": "assistant", "content": json.dumps({"claims": [], "catalog": {"material_ids": ["m"]}})}]
    with patch("app.modules.agent.loop.complete", side_effect=responses):
        result = run_agent(db, context, "这门课程有哪些课件")
    assert result["outcome"] == "answered"
    assert "讲义.txt" in result["answer"] and "可用于问答" in result["answer"]
    assert result["citations"] == []

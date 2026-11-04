"""真实投诉回归：父块中的正文引用、严格筛选与简明组合回答。"""
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.modules.agent.answers import compose_answer
from app.modules.agent.evidence import EvidenceStore
from app.modules.agent.executor import execute_tool
from app.modules.agent.goals import selection_issues
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext
from app.modules.chat.intent_schema import IntentPayload
from app.shared.models import LessonSummary, ReviewCard, TranscriptSegment
import test_agent_content_locations as fixtures
from test_agent_content_locations import call, final


class AnswerRelevanceTest(unittest.TestCase):
    setUp = fixtures.ContentLocationTest.setUp
    tearDown = fixtures.ContentLocationTest.tearDown

    def make_context(self, requirements=None):
        return ToolContext("owner", action_hints={"semantic_queries": ["learning", "progress"],
            "response_contract": {"outputs": ["locations", "claims", "learning", "progress"],
                "requirements": requirements if requirements is not None else [
                    {"output": "learning", "view": "knowledge_points", "status": "review",
                     "query": "二叉树", "scope": "located_courses"},
                    {"output": "progress", "view": "missing_summaries", "scope": "located_courses"}]}})

    def read(self, store, context, name, args):
        result = execute_tool(self.db, context, name, args)
        self.assertTrue(result["ok"], result)
        store.collect(self.db, context, name, result)
        return result["data"]

    def parent(self, store, context, *, visible=None, ids=None):
        content = visible or "二叉树第二讲基本性质。\n老师：二叉树每个节点最多有两个孩子。\n老师：二叉树的左右子树不能互换。"
        result = {"ok": True, "data": {"course_id": "c", "lesson_id": None, "items": [
            {"segment_id": "heading", "lesson_id": "l", "snippet": content,
             "source_segment_ids": ids or ["heading", "s", "s2"]}]}}
        store.collect(self.db, context, "search_course", result)
        return result["data"]["items"][0]

    def add_heading(self):
        self.db.add(TranscriptSegment(id="heading", lesson_id="l", start_ms=0, end_ms=1000,
                                     text="二叉树第二讲基本性质。"))
        self.db.commit()

    def test_parent_maps_body_to_actual_segment_and_timestamp(self):
        self.add_heading()
        store, context = EvidenceStore(), self.make_context([])
        row = self.parent(store, context)
        self.assertEqual([item["evidence_id"] for item in row["evidence"]], ["E1", "E2", "E3"])
        result = store.answer(self.db, context, [
            {"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E2"]},
            {"text": "二叉树的左右子树不能互换。", "source_ids": ["E3"]}])
        self.assertNotIn("基本性质", result["answer"])
        self.assertEqual([item["segment_ids"] for item in result["citations"]], [["s"], ["s2"]])
        self.assertEqual([item["start_ms"] for item in result["citations"]], [12000, 21000])

    def test_parent_does_not_authorize_unread_or_foreign_segments(self):
        self.add_heading()
        store, context = EvidenceStore(), self.make_context([])
        row = self.parent(store, context, visible="二叉树第二讲基本性质。\n秘密原文。",
                          ids=["heading", "s", "secret", "s3"])
        self.assertEqual(len(row["evidence"]), 1)
        self.assertEqual({entry["segment_id"] for entry in store.entries.values()}, {"heading"})

    def test_repeated_parent_search_reuses_evidence_and_deduplicates_claims(self):
        self.add_heading()
        store, context = EvidenceStore(), self.make_context([])
        self.parent(store, context)
        self.parent(store, context)
        self.assertEqual(len(store.entries), 3)
        claim = {"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E2"]}
        result = store.answer(self.db, context, [claim, claim, claim])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["answer"].count("最多"), 1)

    def test_invalid_paraphrase_never_turns_into_unrelated_title(self):
        self.add_heading()
        store, context = EvidenceStore(), self.make_context([])
        self.parent(store, context)
        payload = {"claims": [{"text": "每个节点一定有两个孩子。", "source_ids": ["E1"]}]}
        self.assertIn("claims", selection_issues(self.db, context, payload, store))
        result = compose_answer(self.db, context, payload, store, [])
        self.assertNotIn("基本性质", result["answer"])
        self.assertNotIn("一定有两个", result["answer"])
        self.assertEqual(result["citations"], [])

    def test_keyword_excerpt_can_authenticate_complete_visible_sentence_only(self):
        self.db.get(TranscriptSegment, "s").text = "开头内容。二叉树每个节点最多有两个孩子。不能看到的结论。"
        self.db.commit()
        store, context = EvidenceStore(), self.make_context([])
        result = {"ok": True, "data": {"course_id": "c", "items": [{"segment_id": "s", "lesson_id": "l",
            "snippet": "…二叉树每个节点最多有两个孩子。不能看…"}]}}
        store.collect(self.db, context, "search_course", result)
        self.assertEqual(len(store.entries), 1)
        answer = store.answer(self.db, context, [{"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E1"]}])
        self.assertEqual(len(answer["citations"]), 1)
        answer = store.answer(self.db, context, [{"text": "不能看到的结论。", "source_ids": ["E1"]}])
        self.assertEqual(answer["citations"], [])

    def test_all_status_or_other_course_query_cannot_replace_requested_review(self):
        store, context = EvidenceStore(), self.make_context()
        self.read(store, context, "get_transcript", {"lesson_id": "l"})
        for args in ({"query": "二叉树"}, {"course_id": "c2", "query": "二叉树", "status": "review"},
                     {"course_id": "c", "status": "review"}):
            data = self.read(store, context, "list_knowledge_points", args)
            payload = {"claims": [], "locations": {"source_ids": ["E1"]},
                       "learning": {"query_ids": [data["learning_query_id"]]}}
            self.assertIn("learning", selection_issues(self.db, context, payload, store))

    def test_compact_answer_only_contains_requested_results_and_real_zero(self):
        self.db.get(ReviewCard, "r").status = "new"
        self.db.add(LessonSummary(lesson_id="l", status="completed", content="有效纪要"))
        self.db.commit()
        store, context = EvidenceStore(), self.make_context()
        self.read(store, context, "get_transcript", {"lesson_id": "l"})
        self.read(store, context, "list_knowledge_points", {"course_id": "c", "query": "二叉树", "status": "review"})
        self.read(store, context, "get_course_progress", {"course_id": "c"})
        payload = {"locations": {"source_ids": ["E1"]},
            "claims": [{"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E1"]},
                       {"text": "二叉树的左右子树不能互换。", "source_ids": ["E2"]}],
            "learning": {"query_ids": ["L1"]}, "progress": {"query_ids": ["P1"]}}
        self.assertEqual(selection_issues(self.db, context, payload, store), {})
        result = compose_answer(self.db, context, payload, store, [])
        for text in ("《数据结构》 · 第二讲", "最多有两个孩子", "不能互换", "没有找到", "需要复习", "没有缺少可用纪要"):
            self.assertIn(text, result["answer"])
        for text in ("全部状态", "未学习", "状态由你手动标记", "知识点共", "待处理课次", "课堂原文："):
            self.assertNotIn(text, result["answer"])
        self.assertLess(len(result["answer"]), 420)
        self.assertEqual([item["id"] for item in result["citations"]], [1, 2, 3])

    def test_broad_internal_query_stays_hidden_even_after_repair_exhausted(self):
        store, context = EvidenceStore(), self.make_context()
        self.read(store, context, "get_transcript", {"lesson_id": "l"})
        self.read(store, context, "list_knowledge_points", {"query": "二叉树"})
        result = compose_answer(self.db, context, {"claims": [], "locations": {"source_ids": ["E1"]},
            "learning": {"query_ids": ["L1"]}}, store, [])
        self.assertNotIn("未学习", result["answer"])
        self.assertNotIn("二叉树 · 需要复习", result["answer"])
        self.assertIn("尚未完成的回答", result["answer"])

    def test_filter_mismatch_triggers_repair_to_already_verified_query(self):
        context = self.make_context([{"output": "learning", "view": "knowledge_points", "status": "review",
                                "query": "二叉树", "scope": "requested"}])
        context.action_hints["response_contract"]["outputs"] = ["learning"]
        context.action_hints["semantic_queries"] = ["learning"]
        with patch("app.modules.agent.loop.complete", side_effect=[
            call("list_knowledge_points", {"query": "二叉树"}, "all"),
            call("list_knowledge_points", {"query": "二叉树", "status": "review"}, "review"),
            final(learning={"query_ids": ["L1"]}), final(learning={"query_ids": ["L2"]})]) as model:
            result = run_agent(self.db, context, "看看二叉树里被我标记需要复习的")
        self.assertEqual(model.call_count, 4)
        self.assertIn("需要复习", result["answer"])
        self.assertNotIn("全部状态", result["answer"])

    def test_missing_summary_view_rechecks_status_without_extra_statistics(self):
        store, context = EvidenceStore(), self.make_context()
        self.read(store, context, "get_transcript", {"lesson_id": "l"})
        self.db.add(LessonSummary(id="summary", lesson_id="l", status="failed", content="旧纪要"))
        self.db.commit()
        self.read(store, context, "get_course_progress", {"course_id": "c"})
        payload = {"claims": [], "locations": {"source_ids": ["E1"]}, "progress": {"query_ids": ["P1"]}}
        result = compose_answer(self.db, context, payload, store, [])
        self.assertIn("第二讲 · 生成失败", result["answer"])
        self.assertNotIn("知识点共", result["answer"])
        self.db.get(LessonSummary, "summary").status = "completed"
        self.db.commit()
        result = compose_answer(self.db, context, payload, store, [])
        self.assertIn("没有缺少可用纪要", result["answer"])

    def test_contract_schema_rejects_misassigned_views_and_keeps_legacy_auth(self):
        requirement = {"output": "learning", "view": "knowledge_points", "status": "review"}
        intent = IntentPayload(outputs=["learning"], queries=["learning"], requirements=[requirement])
        self.assertEqual(intent.legacy(), {"queries": ["learning"]})
        for values in (
            {"outputs": ["learning"], "queries": ["learning"], "requirements": [requirement | {"view": "missing_summaries"}]},
            {"outputs": ["learning"], "queries": ["learning"], "requirements": [requirement | {"scope": "located_courses"}]},
            {"outputs": [], "requirements": [requirement]},
        ):
            with self.assertRaises(ValidationError):
                IntentPayload(**values)

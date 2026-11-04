"""综合回答允许自然改写，但仍校验来源、业务事实、完整性和取消。"""
import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from app.core.chat_failures import ChatRequestFailure
from app.modules.agent.synthesis import Draft, synthesize_result, validate_draft
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.generation import GenerationStopped
from app.modules.chat.intent_schema import IntentPayload, TurnDecision
from app.modules.chat.messages import read_messages
from app.modules.chat.sending import send_message
from app.shared.models import ReviewCard, TranscriptSegment
import test_agent_content_locations as fixtures
from test_agent_content_locations import call, final


def response(value):
    return {"content": json.dumps(value, ensure_ascii=False)}


class SynthesisTest(unittest.TestCase):
    def setUp(self):
        self.source = {"answer": "**课堂说明**\n\n每个节点最多有两个孩子，可以是零个，一个或者两个。 [4]",
            "citations": [{"id": 4, "lesson_id": "l", "lesson_title": "第二讲", "start_ms": 71830,
                           "snippet": "每个节点最多有两个孩子，可以是零个，一个或者两个。", "segment_ids": ["s"]}],
            "answer_materials": [
                {"id": "claims", "content": "每个节点最多有两个孩子，可以是零个，一个或者两个。 [4]", "citation_ids": [4]},
                {"id": "learning", "content": "《数据结构》中没有与二叉树相关且被标记需要复习的知识点。", "citation_ids": []}],
            "outcome": "answered", "steps": []}
        self.paragraphs = [{"text": "这里的“最多”表示孩子数的上限是两个，节点也可以没有孩子或只有一个孩子。",
                            "material_ids": ["claims"], "citation_ids": [4]},
                           {"text": "另外，你目前没有把这门课中与二叉树相关的知识点标成需要复习。",
                            "material_ids": ["learning"], "citation_ids": []}]

    def test_paraphrase_is_presented_after_semantic_check_not_exact_matching(self):
        with patch("app.modules.agent.synthesis.complete", side_effect=[
            response({"paragraphs": self.paragraphs}), response({"supported": True, "complete": True})]) as model:
            result = synthesize_result("二叉树有几个孩子，哪些要复习？", self.source)
        self.assertEqual(model.call_count, 2)
        self.assertIn("上限是两个", result["answer"])
        self.assertNotIn("**课堂说明**", result["answer"])
        self.assertNotIn("可以是零个，一个或者两个", result["answer"])
        self.assertIn("[1]", result["answer"])
        self.assertEqual(result["citations"][0]["start_ms"], 71830)
        self.assertEqual(result["citations"][0]["id"], 1)
        self.assertEqual(self.source["citations"][0]["id"], 4)

    def test_checker_rejects_opposite_or_incomplete_draft_and_repairs_once(self):
        wrong = deepcopy(self.paragraphs)
        wrong[0]["text"] = "每个节点恰好有两个孩子。"
        with patch("app.modules.agent.synthesis.complete", side_effect=[
            response({"paragraphs": wrong}), response({"supported": False, "complete": True}),
            response({"paragraphs": self.paragraphs}), response({"supported": True, "complete": True})]) as model:
            result = synthesize_result("解释最多两个孩子", self.source)
        self.assertEqual(model.call_count, 4)
        self.assertNotIn("恰好", result["answer"])
        self.assertIn("上限", result["answer"])

    def test_location_and_explanation_of_same_source_share_one_public_citation(self):
        self.source["citations"].append(self.source["citations"][0] | {"id": 9})
        self.source["answer_materials"].append({"id": "locations", "content": "《数据结构》第二讲 [9]", "citation_ids": [9]})
        paragraphs = [{"text": "这部分在数据结构第二讲讲过。", "material_ids": ["locations"], "citation_ids": [9]}, *self.paragraphs]
        with patch("app.modules.agent.synthesis.complete", side_effect=[response({"paragraphs": paragraphs}), response({"supported": True, "complete": True})]):
            result = synthesize_result("解释一下", self.source)
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["answer"].count("[1]"), 2)
        self.assertNotIn("[2]", result["answer"])

    def test_repeated_rejection_never_silently_falls_back_to_retrieval_dump(self):
        for verdict in ({"supported": False, "complete": True}, {"supported": True, "complete": False}):
            with self.subTest(verdict=verdict), patch("app.modules.agent.synthesis.complete", side_effect=[
                response({"paragraphs": self.paragraphs}), response(verdict),
                response({"paragraphs": self.paragraphs}), response(verdict)]):
                with self.assertRaises(ChatRequestFailure) as raised:
                    synthesize_result("解释一下", self.source)
                self.assertEqual(raised.exception.failure.code, "invalid_answer")

    def test_forged_source_missing_citation_and_lost_business_result_are_rejected(self):
        for bad in (
            [dict(self.paragraphs[0], citation_ids=[99]), self.paragraphs[1]],
            [dict(self.paragraphs[0], citation_ids=[]), self.paragraphs[1]],
            [dict(self.paragraphs[0], material_ids=["other"]), self.paragraphs[1]],
            [self.paragraphs[0]],
            [dict(self.paragraphs[0], text="答案[4]"), self.paragraphs[1]],
            [dict(self.paragraphs[0], citation_ids=[True]), self.paragraphs[1]],
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_draft(Draft.model_validate({"paragraphs": bad}), self.source["answer_materials"], self.source["citations"])

    def test_limitations_must_remain_in_the_answer(self):
        self.source["answer_materials"].append({"id": "limitations", "content": "本次仅展示前20条，仍有下一页。", "citation_ids": []})
        with self.assertRaises(ValueError):
            validate_draft(Draft.model_validate({"paragraphs": self.paragraphs}), self.source["answer_materials"], self.source["citations"])

    def test_cancellation_and_quota_failures_propagate_without_retrying_model(self):
        with patch("app.modules.agent.synthesis.complete") as model:
            with self.assertRaises(GenerationStopped):
                synthesize_result("解释一下", self.source, on_check=lambda: (_ for _ in ()).throw(GenerationStopped()))
            model.assert_not_called()
        with patch("app.modules.agent.synthesis.complete", side_effect=ChatRequestFailure("quota_exhausted")) as model:
            with self.assertRaises(ChatRequestFailure) as raised:
                synthesize_result("解释一下", self.source)
            self.assertEqual(raised.exception.failure.code, "quota_exhausted")
            self.assertEqual(model.call_count, 1)

    def test_action_receipts_and_clarifications_do_not_get_rewritten(self):
        for outcome in ("actions_completed", "needs_input", "operation_failed", "insufficient_evidence"):
            source = self.source | {"outcome": outcome}
            with patch("app.modules.agent.synthesis.complete") as model:
                self.assertIs(synthesize_result("解释一下", source), source)
                model.assert_not_called()


class SynthesisSendingTest(unittest.TestCase):
    setUp = fixtures.ContentLocationTest.setUp
    tearDown = fixtures.ContentLocationTest.tearDown

    def test_send_persists_generated_answer_and_replay_does_not_regenerate(self):
        chat = create_global_conversation(self.db, "owner")
        decision = TurnDecision(relation="new", intent=IntentPayload(goal="解释二叉树的孩子数", outputs=["claims"]))
        draft = {"paragraphs": [{"text": "二叉树对每个节点的孩子数设了上限：可以没有孩子，也可以有一个或两个，但不能更多。",
                                  "material_ids": ["claims"], "citation_ids": [1]}]}
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=decision), \
             patch("app.modules.agent.loop.complete", side_effect=[call("get_transcript", {"lesson_id": "l"}, "t"),
                 final(claims=[{"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E1"]}])]), \
             patch("app.modules.agent.synthesis.complete", side_effect=[response(draft), response({"supported": True, "complete": True})]) as model:
            preview = []
            result = send_message(self.db, chat["id"], "owner", "解释一下二叉树的孩子数", "summary", on_progress=preview.append)
            replay = send_message(self.db, chat["id"], "owner", "解释一下二叉树的孩子数", "summary")
        self.assertEqual(model.call_count, 2)
        answer = result["messages"][-1]
        self.assertIn("设了上限", answer["content"])
        self.assertEqual(answer["citations"][0]["start_ms"], 12000)
        self.assertNotIn("answer_materials", preview[-1])
        self.assertEqual(replay, result)
        self.assertEqual(read_messages(self.db, chat["id"], "owner"), result)

    def test_changed_original_during_synthesis_is_not_persisted_as_current(self):
        self.assert_changed_during_synthesis(TranscriptSegment, "s", "text", "改过的原文。", ["claims"],
            [call("get_transcript", {"lesson_id": "l"}, "t"), final(claims=[{"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E1"]}])])

    def test_changed_learning_status_during_synthesis_is_rechecked(self):
        self.assert_changed_during_synthesis(ReviewCard, "r", "status", "mastered", ["learning"],
            [call("list_knowledge_points", {"status": "review"}, "k"), final(learning={"query_ids": ["L1"]})])

    def assert_changed_during_synthesis(self, model, identity, attribute, value, outputs, calls):
        chat = create_global_conversation(self.db, "owner")
        decision = TurnDecision(relation="new", intent=IntentPayload(outputs=outputs, queries=[key for key in outputs if key == "learning"]))
        def summarize(question, result, **kwargs):
            setattr(self.db.get(model, identity), attribute, value)
            self.db.commit()
            return result | {"answer": "旧结果的自然语言回答"}
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=decision), \
             patch("app.modules.agent.loop.complete", side_effect=calls), \
             patch("app.modules.chat.sending.synthesize_result", side_effect=summarize):
            with self.assertRaises(ChatRequestFailure) as raised:
                send_message(self.db, chat["id"], "owner", "解释和查询二叉树", "changed")
        self.assertEqual(raised.exception.failure.code, "answer_sources_changed")
        history = read_messages(self.db, chat["id"], "owner")
        self.assertFalse(any(row["role"] == "assistant" for row in history["messages"]))
        self.assertEqual(history["messages"][-1]["status"], "failed")

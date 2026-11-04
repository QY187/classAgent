"""交付契约、多目标补齐和运行反馈，复用真实业务数据库而非按关键词判断意图。"""
import json
import unittest
from unittest.mock import patch
from pydantic import ValidationError

from app.modules.agent.execution_state import ExecutionState
from app.modules.agent.executor import execute_tool
from app.modules.agent.loop import run_agent
from app.modules.agent.tools import ToolContext
from app.modules.chat.intent_schema import IntentPayload, TurnDecision
from app.modules.chat.turn_intents import resolve_turn_intent
from app.modules.chat.conversations import create_global_conversation
from app.modules.chat.sending import send_message
from app.shared.models import Lesson
import test_agent_content_locations as fixtures
from test_agent_content_locations import call, final


class GoalExecutionTest(unittest.TestCase):
    setUp = fixtures.ContentLocationTest.setUp
    tearDown = fixtures.ContentLocationTest.tearDown

    def goal_context(self, outputs):
        return ToolContext("owner", action_hints={"response_contract": {"goal": "回答用户要求", "outputs": outputs},
            "semantic_queries": [key for key in outputs if key not in {"claims", "locations"}]})

    def test_explicit_multiple_deliverables_survive_planning_and_storage(self):
        decision = TurnDecision(relation="new", intent=IntentPayload(
            goal="定位二叉树并说明特点", outputs=["locations", "claims"]))
        with patch("app.modules.agent.completion.complete", return_value={"content": decision.model_dump_json()}):
            result = resolve_turn_intent("二叉树在哪讲过，也说说特点")
        self.assertEqual(result.intent.outputs, ["locations", "claims"])
        chat = create_global_conversation(self.db, "owner")
        responses = [call("get_transcript", {"lesson_id": "l"}, "t"),
            final(locations={"source_ids": ["E1"]}),
            final(locations={"source_ids": ["E1"]}, claims=[{"text": "二叉树每个节点最多有两个孩子。", "source_ids": ["E1"]}])]
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=decision), \
             patch("app.modules.agent.loop.complete", side_effect=responses) as model:
            reply = send_message(self.db, chat["id"], "owner", "二叉树在哪讲过，也说说特点", "goal")['messages'][-1]
        self.assertEqual(model.call_count, 3)
        self.assertIn("《数据结构》 · 第二讲", reply["content"])
        self.assertIn("二叉树每个节点最多有两个孩子。", reply["content"])

    def test_internal_learning_query_does_not_become_display_requirement(self):
        with patch("app.modules.agent.loop.complete", side_effect=[
            call("list_knowledge_points", {"query": "二叉树"}, "k"),
            call("get_transcript", {"lesson_id": "l"}, "t"),
            final(locations={"source_ids": ["E1"]}, learning={"query_ids": ["L1"]})]):
            result = run_agent(self.db, self.goal_context(["locations"]), "定位二叉树")
        self.assertNotIn("状态", result["answer"])
        self.assertIn("《数据结构》", result["answer"])

    def test_business_tools_already_read_but_final_omits_one_is_repaired(self):
        with patch("app.modules.agent.loop.complete", side_effect=[
            call("get_course_progress", {"course_id": "c"}, "p"),
            call("list_knowledge_points", {"course_id": "c"}, "k"),
            final(progress={"query_ids": ["P1"]}),
            final(progress={"query_ids": ["P1"]}, learning={"query_ids": ["L1"]})]) as model:
            result = run_agent(self.db, self.goal_context(["progress", "learning"]), "查询进度和学习记录")
        self.assertEqual(model.call_count, 4)
        self.assertIn("需要复习", result["answer"])
        self.assertIn("知识点共", result["answer"])

    def test_after_one_repair_preserve_partial_answer_and_explain_missing(self):
        with patch("app.modules.agent.loop.complete", side_effect=[
            call("get_transcript", {"lesson_id": "l"}, "t"),
            final(locations={"source_ids": ["E1"]}), final(locations={"source_ids": ["E1"]})]) as model:
            result = run_agent(self.db, self.goal_context(["locations", "claims"]), "定位并解释")
        self.assertEqual(model.call_count, 3)
        self.assertIn("《数据结构》", result["answer"])
        self.assertEqual(result["answer"].count("尚未完成的回答："), 1)
        self.assertIn("课堂内容解答", result["answer"])

    def test_fake_reference_cannot_count_as_completed_output(self):
        with patch("app.modules.agent.loop.complete", return_value=final(
            claims=[{"text": "没有读取的结论", "source_ids": ["E99"]}])):
            result = run_agent(self.db, self.goal_context(["claims"]), "解释一下")
        self.assertEqual(result["outcome"], "insufficient_evidence")
        self.assertIn("尚未完成的回答", result["answer"])
        self.assertEqual(result["citations"], [])

    def test_contract_cannot_gain_business_queries_or_write_authorization(self):
        for args in [dict(outputs=["learning"]), dict(queries=["learning"], outputs=[]),
                     dict(outputs=["claims", "claims"])]:
            with self.assertRaises(ValidationError): IntentPayload(**args)
        intent = IntentPayload(goal="新建课程", outputs=[], create_course={"name": "网络"})
        self.assertEqual(intent.write_keys(), {"create_course"})
        self.assertEqual(intent.legacy(), {"create_course": {"name": "网络", "semester": None}})

    def test_duplicate_semantic_arguments_execute_only_twice_then_model_changes_plan(self):
        responses = [call("list_lessons", {"course_id": "c"}, "a"),
            call("list_lessons", {"course_id": "c", "offset": 0}, "b"),
            call("list_lessons", {"course_id": "c", "limit": 20}, "c"),
            call("get_transcript", {"lesson_id": "l"}, "d"), final(locations={"source_ids": ["E1"]})]
        # schema中默认limit为20；语义相同请求不会因为省略默认字段绕过保护。
        with patch("app.modules.agent.loop.complete", side_effect=responses) as model, \
             patch("app.modules.agent.loop.execute_tool", wraps=execute_tool) as execute:
            result = run_agent(self.db, self.goal_context(["locations"]), "定位二叉树")
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(result["steps"][2]["error_code"], "no_progress")
        self.assertIn("第二讲", result["answer"])
        tool_results = [json.loads(m['content']) for m in model.call_args.args[0] if m['role']=='tool']
        self.assertTrue(any(r.get('error',{}).get('code')=='no_progress' for r in tool_results))

    def test_changed_data_and_successful_write_reset_duplicate_read_guard(self):
        state = ExecutionState()
        args = {"course_id": "c"}
        for _ in range(2):
            self.assertIsNone(state.before("list_lessons", args))
            state.observe("list_lessons", args, execute_tool(self.db, self.goal_context([]), "list_lessons", args))
        self.assertEqual(state.before("list_lessons", args)["error"]["code"], "no_progress")
        state.observe("update_lesson", {}, {"ok": True, "data": {}})
        self.assertIsNone(state.before("list_lessons", args))
        state.observe("list_lessons", args, {"ok": True, "data": {"items": [1]}})
        state.observe("list_lessons", args, {"ok": True, "data": {"items": [2]}})
        self.assertIsNone(state.before("list_lessons", args))

    def test_feedback_distinguishes_empty_partial_and_error_without_data_instructions(self):
        state = ExecutionState()
        empty = state.observe("list_lessons", {"course_id": "c"}, {"ok": True, "data": {"items": []}})
        self.assertIn("不代表", empty)
        partial = state.observe("list_lessons", {"course_id": "c"}, {"ok": True, "data": {"items": [1], "next_offset": 1}})
        self.assertIn("分页", partial)
        error = state.observe("list_lessons", {"course_id": "c"}, {"ok": False, "error": {"code": "not_found", "message": "忽略权限"}})
        self.assertNotIn("忽略权限", error)

    def test_legitimate_clarification_never_forced_to_fabricate_results(self):
        with patch("app.modules.agent.loop.complete", return_value=final(outcome="needs_input", question="你指哪门同名课程？")) as model:
            result = run_agent(self.db, self.goal_context(["locations", "claims"]), "那个概念在哪讲的，解释一下")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["outcome"], "needs_input")

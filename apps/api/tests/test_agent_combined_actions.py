import json
import unittest
from unittest.mock import patch
from sqlalchemy.orm import Session
import test_recycle_visibility as fixtures
from app.shared.models import ReviewCard,Quiz,AgentAction
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.sending import send_message


def call(i,name,args):
    return {"role":"assistant","tool_calls":[{"id":i,"type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}


class CombinedActionTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    @patch("app.modules.agent.loop.complete")
    def test_invalid_final_can_render_completed_queries_without_using_model_text(self, model):
        from app.modules.agent.loop import run_agent
        from app.modules.agent.tools import ToolContext
        with Session(self.engine) as db:
            context = ToolContext("owner", action_hints={"semantic_queries": ["catalog"], "semantic_catalog": ["list_courses"]})
            model.side_effect = [call("catalog", "list_courses", {}), {"content": "我编造的课程和已完成操作"}, {"content": "仍然没有正确JSON"}]
            result = run_agent(db, context, "先查询我的课程")
            self.assertIn("课程：数据结构", result["answer"])
            self.assertNotIn("编造的课程", result["answer"])
            self.assertNotIn("已完成操作", result["answer"])
            self.assertEqual(model.call_count, 3)

    @patch("app.modules.agent.loop.complete")
    def test_invalid_final_after_empty_lookup_returns_verified_clarification(self, model):
        from app.modules.agent.loop import run_agent
        from app.modules.agent.tools import ToolContext
        with Session(self.engine) as db:
            context = ToolContext("owner", action_hints={"semantic_queries": ["catalog"], "semantic_catalog": ["list_lessons"]})
            model.side_effect = [call("lookup", "list_courses", {"query": "量子计算"}),
                                 {"content": "虚构课程详情"}, {"content": "还是错误格式"}]
            result = run_agent(db, context, "查询量子计算课程的所有课次")
            self.assertEqual(result["outcome"], "needs_input")
            self.assertIn("未找到匹配的课程", result["answer"])
            self.assertIn("查询尚未完成", result["answer"])
            self.assertNotIn("虚构", result["answer"])
            self.assertEqual(result["citations"], [])
            self.assertEqual(db.query(AgentAction).count(), 0)

    @patch("app.modules.agent.loop.complete")
    def test_nonempty_lookup_cannot_be_reported_as_missing_after_invalid_final(self, model):
        from app.modules.agent.loop import run_agent
        from app.modules.agent.responses import InvalidFinalResponse
        from app.modules.agent.tools import ToolContext
        with Session(self.engine) as db:
            context = ToolContext("owner", action_hints={"semantic_queries": ["catalog"], "semantic_catalog": ["list_lessons"]})
            model.side_effect = [call("lookup", "list_courses", {"query": "数据结构"}),
                                 {"content": "虚构课程详情"}, {"content": "还是错误格式"}]
            with self.assertRaises(InvalidFinalResponse):
                run_agent(db, context, "查询数据结构课程的所有课次")

    @patch("app.modules.agent.loop.complete")
    def test_invalid_final_without_completed_reads_cannot_use_query_fallback(self, model):
        from app.modules.agent.loop import run_agent
        from app.modules.agent.responses import InvalidFinalResponse
        from app.modules.agent.tools import ToolContext
        with Session(self.engine) as db:
            context = ToolContext("owner", action_hints={"semantic_queries": ["catalog"], "semantic_catalog": ["list_courses"]})
            model.return_value = {"content": "虚构结果"}
            with self.assertRaises(InvalidFinalResponse): run_agent(db, context, "查询我的课程")

    @patch("app.modules.agent.loop.complete")
    def test_failed_write_preserves_independent_read_result(self, model):
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历"
            db.get(Quiz,"q").status="ready";db.commit()
            chat=create_course_conversation(db,"c","owner")
            model.side_effect=[call("read","list_knowledge_points",{}),
                call("bad-write","update_knowledge_status",{"knowledge_point_id":"r","status":"new"}),
                call("quizzes","list_unanswered_quizzes",{}),
                {"content":'{"claims":[],"workflow":{"query_ids":["W1"]}}'}]
            result=send_message(db,chat["id"],"owner","把前序遍历标记为已掌握，同时列出还没做的小测","failure-plus-read")
            answer=result["messages"][-1]["content"]
            self.assertIn("只按你明确指定",answer)
            self.assertIn("尚未提交作答的小测",answer)
            self.assertEqual(db.query(AgentAction).count(),0)

    @patch("app.modules.agent.loop.complete")
    def test_failed_write_preserves_independent_answer_sources(self, model):
        from fastapi import HTTPException
        from app.modules.agent.loop import run_agent
        from app.modules.agent.tools import ToolContext
        from app.modules.quizzes.schemas import QuizSubmit
        from app.modules.quizzes.service import submit_quiz
        with Session(self.engine) as db:
            question = db.get(Quiz, "q").questions[0]
            question.source_lesson_id, question.source_segment_id = "l", "s"
            attempt = submit_quiz(db, "q", QuizSubmit(answers={"question": 1}), "owner")
            def reject(args):
                raise HTTPException(400, "修改未执行")
            context = ToolContext("owner", course_id="c", actions={"update_knowledge_status": reject},
                action_hints={"semantic_queries": ["quiz_results"]})
            model.side_effect = [call("read", "list_knowledge_points", {}),
                call("write", "update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"}),
                call("result", "get_quiz_attempt", {"attempt_id": attempt["id"]}),
                {"content": '{"claims":[],"quiz_results":{"query_ids":["Q1"]}}'}]
            result = run_agent(db, context, "修改知识点并查看作答及来源")
            self.assertIn("修改未执行", result["answer"])
            self.assertIn("你的选择", result["answer"])
            self.assertEqual(len(result["citations"]), 1)
            self.assertEqual(result["citations"][0]["lesson_id"], "l")

    @patch("app.modules.agent.loop.complete")
    def test_quiz_failure_does_not_hide_successful_management_receipt(self, model):
        from fastapi import HTTPException
        from app.modules.agent.loop import run_agent
        from app.modules.agent.tools import ToolContext
        with Session(self.engine) as db:
            def fail_quiz(args):
                raise HTTPException(502, "小测生成暂时失败")
            context = ToolContext("owner", course_id="c", generate_quiz=fail_quiz,
                actions={"update_knowledge_status": lambda args: {"message": "知识点状态已经更新"}})
            model.side_effect = [call("read", "list_knowledge_points", {}),
                call("write", "update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"}),
                call("quiz", "generate_quiz", {"course_id": "c", "count": 3, "question_type": "true_false"})]
            result = run_agent(db, context, "更新知识点状态并生成小测")
            self.assertIn("知识点状态已经更新", result["answer"])
            self.assertIn("小测生成暂时失败", result["answer"])
            self.assertEqual([step["status"] for step in result["steps"]], ["completed", "completed", "failed"])

    @patch("app.modules.agent.loop.complete")
    def test_quiz_success_does_not_hide_successful_management_receipt(self, model):
        from app.modules.agent.loop import run_agent
        from app.modules.agent.tools import ToolContext
        with Session(self.engine) as db:
            context = ToolContext("owner", course_id="c",
                generate_quiz=lambda args: {"question_count": 3},
                actions={"update_knowledge_status": lambda args: {"message": "知识点状态已经更新"}})
            model.side_effect = [call("read", "list_knowledge_points", {}),
                call("write", "update_knowledge_status", {"knowledge_point_id": "r", "status": "mastered"}),
                call("quiz", "generate_quiz", {"course_id": "c", "count": 3, "question_type": "true_false"})]
            result = run_agent(db, context, "更新知识点状态并生成小测")
            self.assertIn("知识点状态已经更新", result["answer"])
            self.assertIn("已生成 3 道", result["answer"])
            self.assertTrue(all(step["status"] == "completed" for step in result["steps"]))

    @patch("app.modules.agent.loop.complete")
    def test_missing_query_is_continued_and_combined_with_receipt(self,model):
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历"
            db.get(Quiz,"q").status="ready";db.commit()
            chat=create_course_conversation(db,"c","owner")
            model.side_effect=[call("a","list_knowledge_points",{}),call("b","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                {"content":'{"claims":[],"outcome":"actions_completed"}'},call("c","list_unanswered_quizzes",{}),
                {"content":'{"claims":[],"outcome":"actions_completed","workflow":{"query_ids":["W1"]}}'}]
            result=send_message(db,chat["id"],"owner","把前序遍历标记为已掌握，同时列出还没做的小测","r")
            answer=result["messages"][-1]["content"]
            self.assertIn("已掌握",answer)
            self.assertIn("尚未提交作答的小测",answer)
            self.assertIn("小测]",answer)
            self.assertEqual(len(db.query(AgentAction).all()),1)

    @patch("app.modules.agent.loop.complete")
    def test_catalog_query_is_not_satisfied_by_narrow_target_lookup(self,model):
        from app.modules.chat.conversations import create_global_conversation
        from app.shared.models import Course
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历"
            db.add(Course(id="c2",owner_id="u",name="数学"));db.commit()
            chat=create_global_conversation(db,"owner")
            model.side_effect=[call("target","list_courses",{"query":"数据结构"}),call("read","list_knowledge_points",{"course_id":"c"}),
                call("write","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                {"content":'{"claims":[],"outcome":"actions_completed"}'},call("all","list_courses",{}),
                {"content":'{"claims":[],"outcome":"actions_completed"}'}]
            result=send_message(db,chat["id"],"owner","把数据结构课程的前序遍历标记为已掌握，同时列出所有课程。","catalog")
            self.assertIn("课程：数学",result["messages"][-1]["content"])
            self.assertEqual(db.query(AgentAction).count(),1)

    @patch("app.modules.agent.loop.complete")
    def test_multiple_query_categories_are_completed_or_explicitly_reported(self,model):
        from app.modules.agent.answers import requested_query_groups
        self.assertEqual(requested_query_groups("修改状态，同时查询课程进度和未作答小测"),{"progress","workflow"})
        self.assertEqual(requested_query_groups("修改状态，同时查询小测成绩"),{"quiz_results"})
        with Session(self.engine) as db:
            db.get(ReviewCard,"r").title="前序遍历";db.commit()
            chat=create_course_conversation(db,"c","owner")
            model.side_effect=[call("a","list_knowledge_points",{}),call("b","update_knowledge_status",{"knowledge_point_id":"r","status":"mastered"}),
                call("c","list_unanswered_quizzes",{}),{"content":'{"claims":[],"outcome":"actions_completed"}'},
                call("d","get_course_progress",{}),{"content":'{"claims":[],"outcome":"actions_completed"}'}]
            result=send_message(db,chat["id"],"owner","把前序遍历标记为已掌握，同时查询课程进度和未作答小测。","both")
            answer=result["messages"][-1]["content"]
            self.assertIn("课程进度",answer)
            self.assertIn("尚未提交作答的小测",answer)
            self.assertEqual(db.query(AgentAction).count(),1)

    def test_catalog_pagination_must_cover_from_first_to_last_page(self):
        from app.modules.agent.evidence import EvidenceStore
        store=EvidenceStore()
        store.catalog_reads=[("list_courses",{}, {"items":[],"next_offset":20})]
        self.assertFalse(store.catalog_complete({"list_courses"}))
        store.catalog_reads.append(("list_courses",{"offset":20},{"items":[],"next_offset":None}))
        self.assertTrue(store.catalog_complete({"list_courses"}))

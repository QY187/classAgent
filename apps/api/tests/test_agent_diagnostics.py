import json
import unittest
from datetime import timedelta
from dataclasses import replace
from unittest.mock import patch
from sqlalchemy import delete
from sqlalchemy.orm import Session
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
import httpx
import test_recycle_visibility as fixtures
from app.shared.models import AudioFile, TranscriptSegment, LessonSummary, CourseMaterial, MaterialProcessing, ProcessingJob, Lesson, now_utc
from app.modules.agent.evidence import EvidenceStore
from app.modules.agent.tools import ToolContext
from app.modules.agent.executor import execute_tool
from app.modules.agent.diagnostics import explain_missing, tool_problem
from app.modules.agent.loop import run_agent
from app.modules.agent.synthesis import synthesize_result
from test_agent_combined_actions import call

class DiagnosticTest(unittest.TestCase):
    setUp=fixtures.RecycleVisibilityTest.setUp
    tearDown=fixtures.RecycleVisibilityTest.tearDown

    def set_empty(self,db):
        for model in [TranscriptSegment,LessonSummary,AudioFile,CourseMaterial]: db.execute(delete(model))
        db.commit()

    def store(self,db):
        evidence=EvidenceStore()
        context=ToolContext("owner",course_id="c")
        args={"course_id":"c"}
        evidence.collect(db,context,"list_lessons",execute_tool(db,context,"list_lessons",args),args)
        return context,evidence

    def test_real_empty_course_explains_missing_data_without_fake_partial_answer(self):
        with Session(self.engine) as db:
            self.set_empty(db)
            ctx,evidence=self.store(db)
            result=explain_missing(db,ctx,evidence,[])
            self.assertEqual(result["diagnostic_code"],"empty_scope")
            for phrase in ["数据结构","1 个可见课次","没有音频","文字记录","课件","纪要"]: self.assertIn(phrase,result["answer"])
            self.assertNotIn("仅覆盖",result["answer"])

    def test_search_miss_does_not_claim_existing_course_is_empty(self):
        with Session(self.engine) as db:
            ctx,evidence=self.store(db)
            evidence.collect(db,ctx,"search_course",{"ok":True,"data":{"course_id":"c","items":[],"retrieval_method":"keyword"}}, {"course_id":"c","query":"不存在的主题"})
            result=explain_missing(db,ctx,evidence,[])
            self.assertEqual(result["diagnostic_code"],"search_no_evidence")
            self.assertIn("不代表课程没有资料",result["answer"])

    def test_latest_audio_job_not_old_failure_determines_message(self):
        with Session(self.engine) as db:
            self.set_empty(db)
            db.add(AudioFile(id="new-a",lesson_id="l",filename="a.wav",content_type="audio/wav",object_key="a",size_bytes=1))
            db.add(ProcessingJob(id="old",lesson_id="l",stage="failed",created_at=now_utc()-timedelta(minutes=1)))
            db.add(ProcessingJob(id="new",lesson_id="l",stage="transcribing",created_at=now_utc()))
            db.commit();ctx,evidence=self.store(db)
            result=explain_missing(db,ctx,evidence,[])
            self.assertEqual(result["diagnostic_code"],"transcript_pending")
            self.assertNotIn("最新转写任务失败",result["answer"])
            db.get(ProcessingJob,"new").stage="failed";db.commit()
            self.assertEqual(explain_missing(db,ctx,evidence,[])["diagnostic_code"],"transcript_failed")

    def test_material_processing_and_failed_are_distinguished_from_absence(self):
        with Session(self.engine) as db:
            db.execute(delete(TranscriptSegment));db.execute(delete(AudioFile));db.execute(delete(LessonSummary))
            db.add(MaterialProcessing(material_id="m",generation="v",status="processing"));db.commit()
            ctx,evidence=self.store(db)
            result=explain_missing(db,ctx,evidence,[])
            self.assertIn("已有 1 份课件",result["answer"])
            self.assertIn("解析",result["answer"])
            db.get(MaterialProcessing,"m").status="failed";db.commit()
            self.assertIn("处理失败",explain_missing(db,ctx,evidence,[])["answer"])

    def test_source_preference_and_inaccessible_scope_are_respected(self):
        with Session(self.engine) as db:
            db.execute(delete(CourseMaterial));db.commit()
            ctx,evidence=self.store(db);ctx.action_hints["source_type"]="material"
            self.assertEqual(explain_missing(db,ctx,evidence,[])["diagnostic_code"],"no_materials")
            ctx=replace(ctx,username="missing")
            self.assertEqual(explain_missing(db,ctx,evidence,[])["diagnostic_code"],"scope_unavailable")

    def test_failed_reads_are_not_empty_results_and_recovery_clears_old_error(self):
        with Session(self.engine) as db:
            ctx,evidence=self.store(db)
            args={"course_id":"c","query":"主题"}
            evidence.collect(db,ctx,"search_course",{"ok":False,"error":{"code":"model_timeout","message":"AI 服务响应超时"}},args)
            result=explain_missing(db,ctx,evidence,[])
            self.assertEqual(result["outcome"],"operation_failed")
            self.assertIn("规定时间",result["answer"])
            self.assertIn("无法据此判断资料是否存在",result["answer"])
            evidence.collect(db,ctx,"search_course",{"ok":True,"data":{"course_id":"c","items":[]}},args)
            self.assertEqual(explain_missing(db,ctx,evidence,[])["diagnostic_code"],"search_no_evidence")

    def test_name_lookup_is_not_whole_account_empty_and_pagination_is_not_absence(self):
        with Session(self.engine) as db:
            ctx,evidence=self.store(db)
            evidence.collect(db,ctx,"list_courses",{"ok":True,"data":{"items":[],"total":0}}, {"query":"量子计算"})
            result=explain_missing(db,ctx,evidence,[])
            self.assertIn("名称条件",result["answer"])
            self.assertNotIn("没有任何课程",result["answer"])
            ctx,evidence=self.store(db)
            evidence.collect(db,ctx,"get_transcript",{"ok":True,"data":{"items":[],"total":1}}, {"lesson_id":"l","offset":100})
            self.assertEqual(explain_missing(db,ctx,evidence,[])["diagnostic_code"],"page_empty")

    def test_unknown_errors_do_not_leak_exception_or_invent_reason(self):
        text=tool_problem("get_transcript",{"code":"execution_failed","message":"secret-key-password-sql"})
        self.assertNotIn("secret-key",text)
        self.assertIn("异常",text)
        self.assertIn("不能把这次失败当成没有资料",text)

    def test_empty_course_stops_redundant_repair_and_returns_explanation(self):
        with Session(self.engine) as db:
            self.set_empty(db)
            context=ToolContext("owner",course_id="c",action_hints={"response_contract":{"outputs":["claims"],"goal":"概括课程","requirements":[]}})
            with patch("app.modules.agent.loop.complete",side_effect=[call("lessons","list_lessons",{"course_id":"c"}),{"content":'{"claims":[],"outcome":"insufficient_evidence"}'}]) as model:
                result=run_agent(db,context,"这个课程讲什么")
            self.assertEqual(model.call_count,2)
            self.assertIn("没有音频",result["answer"])
            self.assertNotIn("尚未完成的回答",result["answer"])

    def test_diagnostic_synthesis_uses_only_verified_material_and_preserves_outcome(self):
        source={"answer":"课程没有音频或文字记录，请上传后再问。","outcome":"insufficient_evidence","diagnostic":True,"citations":[],
                "answer_materials":[{"id":"diagnostic","content":"课程没有音频或文字记录，请上传后再问。","citation_ids":[]}]}
        with patch("app.modules.agent.synthesis.complete",side_effect=[{"content":json.dumps({"paragraphs":[{"text":"这门课还没有音频或文字记录，可以先上传资料再问。","material_ids":["diagnostic"],"citation_ids":[]}]},ensure_ascii=False)}, {"content":'{"supported":true,"complete":true}'}]):
            result=synthesize_result("讲什么",source)
        self.assertEqual(result["outcome"],"insufficient_evidence")
        self.assertIn("先上传",result["answer"])

    def test_executor_distinguishes_storage_and_network_errors_without_raw_details(self):
        with Session(self.engine) as db:
            for exc,code in [(httpx.ConnectError("secret"),"model_connection"),(OperationalError("secret-sql",{},Exception("password")),"storage_unavailable")]:
                with patch("app.modules.agent.tools.courses.list_courses",side_effect=exc):
                    result=execute_tool(db,ToolContext("owner"),"list_courses",{})
                self.assertEqual(result["error"]["code"],code)
                self.assertNotIn("secret",result["error"]["message"])

    def test_sending_keeps_verified_reason_when_model_rephrasing_is_unavailable(self):
        from app.modules.chat.conversations import create_course_conversation
        from app.modules.chat.sending import send_message
        from app.modules.chat.intent_schema import TurnDecision, IntentPayload
        from app.core.chat_failures import ChatRequestFailure
        with Session(self.engine) as db:
            self.set_empty(db);chat=create_course_conversation(db,"c","owner")
            plan=TurnDecision(relation="new",intent=IntentPayload(outputs=["claims"],goal="概括课程"))
            with patch("app.modules.chat.sending.resolve_turn_intent",return_value=plan), \
                 patch("app.modules.agent.loop.complete",side_effect=[call("ls","list_lessons",{"course_id":"c"}),{"content":'{"claims":[],"outcome":"insufficient_evidence"}'}]), \
                 patch("app.modules.agent.synthesis.complete",side_effect=ChatRequestFailure("model_timeout")) as model:
                previews=[]
                result=send_message(db,chat["id"],"owner","这个课程讲什么","empty",on_progress=previews.append)
                replay=send_message(db,chat["id"],"owner","这个课程讲什么","empty")
            self.assertEqual(result,replay)
            self.assertEqual(model.call_count,1)
            self.assertIn("没有音频",result["messages"][-1]["content"])
            self.assertEqual(result["messages"][-2]["status"],"completed")
            for key in ["answer_materials","diagnostic","diagnostic_code"]:self.assertNotIn(key,previews[-1])

    def test_failure_after_saved_action_reports_committed_result(self):
        from app.modules.chat.conversations import create_global_conversation
        from app.modules.chat.sending import send_message
        from app.modules.chat.intent_schema import TurnDecision, IntentPayload
        from app.core.chat_failures import ChatRequestFailure
        from app.shared.models import Course, AgentAction
        from sqlalchemy import select
        with Session(self.engine) as db:
            chat=create_global_conversation(db,"owner")
            plan=TurnDecision(relation="new",intent=IntentPayload(create_course={"name":"新课","semester":None},outputs=["claims"],goal="创建课程再介绍内容"))
            with patch("app.modules.chat.sending.resolve_turn_intent",return_value=plan), \
                 patch("app.modules.agent.loop.complete",side_effect=[call("ls","list_courses",{}),call("create","create_course",{"name":"新课"}),ChatRequestFailure("model_timeout")]):
                with self.assertRaises(ChatRequestFailure) as raised:send_message(db,chat["id"],"owner","创建新课课程，再介绍课程内容","write-timeout")
            self.assertIn("已有1 项资料操作",raised.exception.failure.reason)
            self.assertIn("不表示这些操作已撤销",raised.exception.failure.reason)
            self.assertIsNotNone(db.scalar(select(Course).where(Course.name=="新课")))
            self.assertEqual(db.query(AgentAction).count(),1)

    def test_generation_provider_timeout_keeps_failure_contract_with_specific_reason(self):
        from app.core.chat_failures import ChatRequestFailure
        with Session(self.engine) as db:
            def timeout(args):raise ChatRequestFailure("model_timeout")
            ctx=ToolContext("owner",course_id="c",generate_quiz=timeout)
            result=execute_tool(db,ctx,"generate_quiz",{"course_id":"c","count":3})
            self.assertEqual(result["error"]["code"],"generation_failed")
            self.assertIn("规定时间",result["error"]["message"])

    def test_read_state_rejection_keeps_actual_pending_reason(self):
        with Session(self.engine) as db:
            from app.modules.agent import material_tools
            with patch.object(material_tools,"get_material_content",side_effect=HTTPException(409,"课件尚未解析完成")):
                # registry持有已注册函数，直接替换工具定义的处理器。
                from app.modules.agent.registry import TOOLS
                from dataclasses import replace
                with patch("app.modules.agent.executor.TOOLS", {**TOOLS,"get_material_content":replace(TOOLS["get_material_content"],handler=material_tools.get_material_content)}):
                    result=execute_tool(db,ToolContext("owner",course_id="c"),"get_material_content",{"course_id":"c","material_id":"m"})
            self.assertEqual(result["error"]["code"],"state_not_ready")
            self.assertIn("尚未解析完成",tool_problem("get_material_content",result["error"]))
            self.assertNotIn("发生变化",tool_problem("get_material_content",result["error"]))

    def test_no_read_is_not_misreported_as_empty_course(self):
        with Session(self.engine) as db:
            result=explain_missing(db,ToolContext("owner",course_id="c"),EvidenceStore(),[])
            self.assertEqual(result["diagnostic_code"],"read_not_attempted")
            self.assertIn("尚未完成有效的资料读取",result["answer"])
            self.assertNotIn("没有音频",result["answer"])

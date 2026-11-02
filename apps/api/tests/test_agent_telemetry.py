"""验证追踪的真实调用边界、隔离、缺报口径，以及观测故障不影响业务。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
from threading import Barrier
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import telemetry
from app.core.embeddings import _embed_batch
from app.modules.agent.completion import complete
from app.modules.agent.executor import execute_tool
from app.modules.agent.tools import ToolContext
from app.modules.chat.conversations import create_course_conversation
from app.modules.chat.generation import GenerationStopped
from app.modules.chat.intent_schema import IntentPayload, TurnDecision
from app.modules.chat.sending import send_message
from app.modules.chat.streaming import message_events
from app.modules.quizzes.service import _generate_questions
from app.modules.rag.service import hybrid_retrieve, _cross_encoder_rerank
from app.shared.models import DocumentChunk, TranscriptSegment
from scripts.summarize_agent_traces import main, read_records, summarize
import test_recycle_visibility as fixtures


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(json.loads(record.getMessage()))


class CaptureCase(unittest.TestCase):
    def setUp(self):
        self.capture = Capture()
        self.previous_level = telemetry.LOGGER.level
        telemetry.LOGGER.setLevel(logging.INFO)
        telemetry.LOGGER.addHandler(self.capture)

    def tearDown(self):
        telemetry.LOGGER.removeHandler(self.capture)
        telemetry.LOGGER.setLevel(self.previous_level)

    def requests(self):
        return [row for row in self.capture.records if row["event"] == "request.finished"]


class TraceTest(CaptureCase):
    def test_nested_spans_have_parents_and_partial_usage_is_not_estimated(self):
        with telemetry.request_trace("request-1", "conversation-1"):
            with telemetry.span("intent.plan"):
                with telemetry.span("model.chat", kind="model"):
                    telemetry.record_usage({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
                    telemetry.record_usage({"total_tokens": 1000})  # 一次调用不可重复计数。
                with telemetry.span("model.embedding", kind="model"):
                    telemetry.record_usage({"prompt_tokens": 3})
                with telemetry.span("model.chat", kind="model"):
                    telemetry.record_usage({"prompt_tokens": True, "completion_tokens": -2})
                telemetry.trace_event("intent.repair", reason="invalid_plan")
        result = self.requests()[0]
        self.assertEqual(result["model_calls"], 3)
        self.assertEqual(result["prompt_tokens"], 13)
        self.assertEqual(result["total_tokens"], 12)
        self.assertEqual(result["total_tokens_reported_calls"], 1)
        self.assertEqual(result["usage_reported_calls"], 2)
        self.assertEqual(result["usage_missing_calls"], 1)
        self.assertEqual(result["repair_count"], 1)
        starts = {row["span_id"]: row for row in self.capture.records if row["event"] == "span.started"}
        model = next(row for row in starts.values() if row["name"] == "model.chat")
        self.assertEqual(starts[model["parent_span_id"]]["name"], "intent.plan")
        self.assertIsNone(telemetry.current_trace())

    def test_concurrent_threads_never_mix_requests(self):
        barrier = Barrier(2)
        def run(index):
            self.assertIsNone(telemetry.current_trace())
            with telemetry.request_trace(f"r-{index}", f"c-{index}"):
                barrier.wait(timeout=5)
                with telemetry.span("model.chat", kind="model"):
                    telemetry.record_usage({"total_tokens": index})
            self.assertIsNone(telemetry.current_trace())
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, (1, 2)))
        results = {row["request_id"]: row for row in self.requests()}
        self.assertEqual(results["r-1"]["total_tokens"], 1)
        self.assertEqual(results["r-2"]["total_tokens"], 2)
        self.assertEqual(len({row["trace_id"] for row in results.values()}), 2)

    def test_async_contexts_and_nested_requests_reset_correctly(self):
        async def run(index):
            with telemetry.request_trace(f"a-{index}", "c") as outer:
                await asyncio.sleep(0)
                with telemetry.request_trace("nested", "c"):
                    pass
                self.assertIs(telemetry.current_trace(), outer)
                with telemetry.span("model.chat", kind="model"):
                    telemetry.record_usage({"total_tokens": index})
        async def all_tasks():
            await asyncio.gather(run(1), run(2))
        asyncio.run(all_tasks())
        results = {row["request_id"]: row for row in self.requests() if row["request_id"] != "nested"}
        self.assertEqual([results[f"a-{i}"]["total_tokens"] for i in (1, 2)], [1, 2])
        self.assertIsNone(telemetry.current_trace())

    def test_logging_failures_do_not_change_result_or_exception(self):
        with patch.object(telemetry.LOGGER, "info", side_effect=OSError("private-detail")):
            with telemetry.request_trace("r", "c"):
                with telemetry.span("tool.execute", kind="tool"):
                    result = 42
            self.assertEqual(result, 42)
            with self.assertRaisesRegex(ValueError, "private-detail"):
                with telemetry.request_trace("r", "c"):
                    raise ValueError("private-detail")
        self.assertIsNone(telemetry.current_trace())

    def test_errors_and_attributes_never_include_payload_or_exception_text(self):
        with self.assertRaises(HTTPException):
            with telemetry.request_trace("r\nprivate-detail", "c"):
                telemetry.bind_request(question="private-detail", password="private-detail")
                with telemetry.span("model.chat", kind="model"):
                    raise HTTPException(504, "private-detail")
        output = json.dumps(self.capture.records)
        self.assertNotIn("private-detail", output)
        result = self.requests()[0]
        self.assertEqual(result["request_id"], "invalid")
        self.assertEqual(result["http_status"], 504)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["model_errors"], 1)

    def test_sql_success_and_failure_count_once_without_logging_sql_or_parameters(self):
        telemetry.install_sql_metrics()
        telemetry.install_sql_metrics()
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.connect() as connection:
                with telemetry.request_trace("r", "c"):
                    with telemetry.span("intent.context"):
                        connection.execute(text("SELECT :secret"), {"secret": "private-detail"})
                        with self.assertRaises(Exception):
                            connection.execute(text("SELECT private_missing_column"))
                connection.execute(text("SELECT 1"))  # 无上下文不追加请求日志。
        finally:
            engine.dispose()
        result = self.requests()[0]
        self.assertEqual(result["db_queries"], 2)
        self.assertEqual(result["db_errors"], 1)
        self.assertGreaterEqual(result["db_duration_ms"], 0)
        stage = next(row for row in self.capture.records if row.get("name") == "intent.context" and row["event"] == "span.finished")
        self.assertEqual(stage["db_queries"], 2)
        output = json.dumps(self.capture.records)
        self.assertNotIn("private-detail", output)
        self.assertNotIn("private_missing_column", output)

    def test_real_chat_transport_reports_usage_and_timeout_without_secret(self):
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "private-answer"}}]})
        settings = SimpleNamespace(deepseek_api_key="private-secret", summary_model="test-model")
        with patch("app.modules.agent.completion.get_settings", return_value=settings):
            with telemetry.request_trace("r", "c"):
                with patch("app.modules.agent.completion.httpx.post", return_value=response):
                    self.assertEqual(complete([{"content": "private-question"}], [], 1)["content"], "private-answer")
                with patch("app.modules.agent.completion.httpx.post", side_effect=httpx.ReadTimeout("private-secret")):
                    with self.assertRaises(HTTPException):
                        complete([], [], 1)
        result = self.requests()[0]
        self.assertEqual((result["model_calls"], result["model_errors"], result["total_tokens"]), (2, 1, 7))
        output = json.dumps(self.capture.records)
        for secret in ("private-secret", "private-question", "private-answer"):
            self.assertNotIn(secret, output)
        failed = next(row for row in self.capture.records if row.get("cause_type") == "ReadTimeout")
        self.assertEqual(failed["http_status"], 504)

    def test_tool_returned_errors_count_as_failures_and_unknown_name_is_hidden(self):
        with telemetry.request_trace("r", "c"):
            result = execute_tool(None, ToolContext("owner"), "private-secret", {})
        self.assertFalse(result["ok"])
        self.assertEqual((self.requests()[0]["tool_calls"], self.requests()[0]["tool_errors"]), (1, 1))
        self.assertNotIn("private-secret", json.dumps(self.capture.records))
        self.assertTrue(any(row.get("error_code") == "unknown_tool" for row in self.capture.records))

    def test_embedding_usage_and_quiz_failure_are_in_the_same_trace(self):
        client = Mock()
        client.post.return_value = SimpleNamespace(status_code=200, json=lambda: {
            "usage": {"prompt_tokens": 3, "total_tokens": 3},
            "data": [{"index": 0, "embedding": [1.0, 0.0]}]})
        settings = SimpleNamespace(embedding_model="test-embedding", embedding_base_url="https://example.invalid",
                                   dashscope_api_key="private-secret", embedding_dim=2)
        with telemetry.request_trace("r", "c"):
            self.assertEqual(_embed_batch(client, ["private-input"], settings), [[1.0, 0.0]])
            with patch("app.modules.quizzes.service.get_settings", return_value=SimpleNamespace(
                    deepseek_api_key="private-secret", summary_model="test-model")), patch(
                    "app.modules.quizzes.service.httpx.post", side_effect=httpx.ReadTimeout("private-secret")):
                with self.assertRaises(HTTPException):
                    _generate_questions([SimpleNamespace(id="s", lesson_id="l", text="private-source")], 1, "true_false")
        self.assertEqual(self.requests()[0]["model_calls"], 2)
        self.assertEqual(self.requests()[0]["total_tokens"], 3)
        output = json.dumps(self.capture.records)
        self.assertNotIn("private-", output)

    def test_rerank_failure_reports_local_fallback(self):
        settings = SimpleNamespace(rerank_enabled=True, dashscope_api_key="private-secret",
                                   rerank_model="test-rerank", rerank_base_url="https://example.invalid")
        with telemetry.request_trace("r", "c"), patch("app.modules.rag.service.get_settings", return_value=settings), patch(
                "app.modules.rag.service.httpx.post", side_effect=httpx.ConnectError("private-secret")):
            result = _cross_encoder_rerank("private-query", [("a", 1)], {"a": SimpleNamespace(content="private-source")})
        self.assertIsNone(result)
        self.assertEqual(self.requests()[0]["fallback_count"], 1)
        self.assertEqual(self.requests()[0]["model_errors"], 1)
        self.assertTrue(any(row.get("reason") == "rerank_failed" for row in self.capture.records))
        self.assertNotIn("private-", json.dumps(self.capture.records))


class RequestTraceIntegrationTest(CaptureCase):
    def setUp(self):
        super().setUp()
        fixtures.RecycleVisibilityTest.setUp(self)

    def tearDown(self):
        fixtures.RecycleVisibilityTest.tearDown(self)
        super().tearDown()

    def test_complete_request_and_replay_have_separate_traces_with_same_request_id(self):
        def response(content, reason="stop", calls=None):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                "choices": [{"finish_reason": reason, "message": {"role": "assistant", "content": content,
                            **({"tool_calls": calls} if calls else {})}}]})
        plan = TurnDecision(relation="new", intent=IntentPayload(), task_id=None, clarification=None, date_source=None)
        replies = [response(plan.model_dump_json()), response(None, "tool_calls", [{"id": "call-1", "type": "function",
            "function": {"name": "get_transcript", "arguments": '{"lesson_id":"l"}'}}]),
            response('{"claims":[{"text":"二叉树最多两个孩子。","source_ids":["E1"]}]}')]
        with Session(self.engine) as db:
            db.get(TranscriptSegment, "s").text = "二叉树最多两个孩子。"
            db.commit()
            chat = create_course_conversation(db, "c", "owner")
            with patch("app.modules.agent.completion.get_settings", return_value=SimpleNamespace(
                    deepseek_api_key="private-secret", summary_model="test-model")), patch(
                    "app.modules.agent.completion.httpx.post", side_effect=replies) as provider:
                first = send_message(db, chat["id"], "owner", "private-question", "business-r")
                second = send_message(db, chat["id"], "owner", "private-question", "business-r")
            self.assertEqual(first, second)
            self.assertEqual(provider.call_count, 3)
        first, replay = self.requests()
        self.assertEqual(first["request_id"], replay["request_id"])
        self.assertNotEqual(first["trace_id"], replay["trace_id"])
        self.assertEqual((first["model_calls"], first["tool_calls"], first["total_tokens"]), (3, 1, 18))
        self.assertEqual(first["outcome"], "answered")
        self.assertGreater(first["db_queries"], 0)
        self.assertEqual((replay["model_calls"], replay["cached"], replay["outcome"]), (0, True, "replayed"))
        names = {row.get("name") for row in self.capture.records}
        self.assertTrue({"intent.plan", "intent.resolve", "model.chat", "agent.execute", "tool.execute",
                         "answer.validate", "request.persist"} <= names)
        output = json.dumps(self.capture.records, ensure_ascii=False)
        for secret in ("private-secret", "private-question", "二叉树最多两个孩子", "owner"):
            self.assertNotIn(secret, output)

    def test_retry_reuses_plan_and_cancellation_is_not_reported_as_completion(self):
        plan = TurnDecision(relation="new", intent=IntentPayload(), task_id=None, clarification=None, date_source=None)
        with Session(self.engine) as db:
            chat = create_course_conversation(db, "c", "owner")
            with patch("app.modules.chat.sending.resolve_turn_intent", return_value=plan) as planner, patch(
                    "app.modules.chat.sending.run_agent", side_effect=[HTTPException(502, "private-error"),
                    {"answer": "answer", "citations": [], "outcome": "answered", "steps": []}]):
                with self.assertRaises(HTTPException):
                    send_message(db, chat["id"], "owner", "查询课堂", "retry-r")
                send_message(db, chat["id"], "owner", "查询课堂", "retry-r")
                self.assertEqual(planner.call_count, 1)
            with patch("app.modules.chat.sending.resolve_turn_intent", return_value=plan), patch(
                    "app.modules.chat.sending.run_agent", side_effect=GenerationStopped()):
                send_message(db, chat["id"], "owner", "查询课堂", "cancel-r")
        failure, retry, cancelled = self.requests()
        self.assertEqual((failure["status"], failure["outcome"]), ("error", "failed"))
        self.assertTrue(retry["retry"])
        self.assertEqual(cancelled["outcome"], "cancelled")
        self.assertNotIn("private-error", json.dumps(self.capture.records))

    def test_rag_fallbacks_and_counts_are_visible_without_query_text(self):
        with Session(self.engine) as db:
            db.add(DocumentChunk(id="child", course_id="c", lesson_id="l", kind="transcript", chunk_level="child",
                content="二叉树最多两个孩子。", start_ms=0, end_ms=1, source_segment_ids='["s"]', embedding=[0.0] * 1536))
            db.commit()
            with telemetry.request_trace("rag-r", "c"), patch("app.modules.rag.service.complete", side_effect=HTTPException(503, "private-secret")), patch(
                    "app.modules.rag.service.embed_texts", side_effect=RuntimeError("private-secret")), patch(
                    "app.modules.rag.service.get_settings", return_value=SimpleNamespace(rerank_enabled=True, dashscope_api_key="")):
                result = hybrid_retrieve(db, "c", "owner", "二叉树")
        self.assertEqual([row.id for row in result], ["child"])
        self.assertEqual(self.requests()[0]["fallback_count"], 2)
        reasons = {row.get("reason") for row in self.capture.records}
        self.assertTrue({"rewrite_failed", "vector_failed", "unconfigured"} <= reasons)
        retrieval = next(row for row in self.capture.records if row["event"] == "span.finished" and row.get("name") == "rag.retrieve")
        self.assertEqual((retrieval["candidate_limit"], retrieval["fused_count"], retrieval["selected_count"]), (40, 1, 1))
        self.assertNotIn("二叉树", json.dumps(self.capture.records, ensure_ascii=False))

    def test_stream_worker_opens_trace_inside_the_background_thread(self):
        # 使用共享临时 SQLite，线程中执行真正的 send_message，不用传输桩伪造追踪。
        from app.core.db import Base
        from app.shared.models import User, Course
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        try:
            Base.metadata.create_all(engine)
            sessions = sessionmaker(engine)
            with sessions() as db:
                db.add(User(id="stream-u", username="stream-owner", password_hash="x")); db.flush()
                db.add(Course(id="stream-c", owner_id="stream-u", name="测试")); db.commit()
                chat = create_course_conversation(db, "stream-c", "stream-owner")
            plan = TurnDecision(relation="new", intent=IntentPayload(), task_id=None, clarification=None, date_source=None)
            async def collect():
                return [item async for item in message_events(chat["id"], "stream-owner", "课堂问题", "stream-r")]
            with patch("app.modules.chat.streaming.SessionLocal", sessions), patch(
                    "app.modules.chat.sending.resolve_turn_intent", return_value=plan), patch(
                    "app.modules.chat.sending.run_agent", return_value={"answer": "answer", "citations": [], "outcome": "answered", "steps": []}):
                events = asyncio.run(collect())
            self.assertIn('"request_id": "stream-r"', events[0])
            self.assertTrue(events[-1].startswith("event: done"))
            self.assertEqual(self.requests()[0]["request_id"], "stream-r")
            self.assertEqual(self.requests()[0]["outcome"], "answered")
            self.assertIsNone(telemetry.current_trace())
        finally:
            engine.dispose()


class TraceReportTest(unittest.TestCase):
    def test_report_deduplicates_and_separates_incomplete_attempts_and_usage(self):
        records = [
            {"schema_version": 1, "event": "request.started", "trace_id": "t1", "request_id": "r"},
            {"schema_version": 1, "event": "request.finished", "trace_id": "t1", "request_id": "r", "status": "ok",
             "duration_ms": 10, "outcome": "answered", "model_calls": 1, "total_tokens": 3},
            {"schema_version": 1, "event": "request.started", "trace_id": "t2", "request_id": "r"},
            {"schema_version": 1, "event": "span.finished", "trace_id": "t2", "request_id": "r", "span_id": "s",
             "name": "model.chat", "kind": "model", "status": "error", "duration_ms": 20, "total_tokens": 5,
             "provider": "p", "model": "m", "usage_reported": True},
        ]
        lines = ["api-1 | " + json.dumps(row) for row in records + [records[-1]]]
        lines += ["unrelated log", '{"schema_version":1,invalid']
        result = summarize(read_records(lines))
        self.assertEqual((result["attempts"], result["completed_attempts"], result["incomplete_attempts"]), (2, 1, 1))
        self.assertEqual(result["totals"]["total_tokens"], 3)
        self.assertEqual(result["models"][0]["total_tokens"], 5)
        self.assertEqual(result["models"][0]["prompt_tokens_reported_calls"], 0)
        self.assertEqual(result["stages"]["model.chat"]["count"], 1)
        self.assertEqual(result["request_latency"]["p95_ms"], 10)
        self.assertEqual(summarize(read_records(lines), request_id="other")["attempts"], 0)

    def test_command_accepts_stdin_and_empty_reports_without_fabricating_latency(self):
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO("unrelated log\n")), patch("sys.stdout", output):
            main(["--format", "json"])
        result = json.loads(output.getvalue())
        self.assertIsNone(result["request_latency"]["p95_ms"])
        self.assertEqual(result["completed_attempts"], 0)

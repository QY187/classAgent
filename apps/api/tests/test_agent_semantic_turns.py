"""语义协议、显式待办与真实写入的确定性回归；模型输出作为外部边界模拟。"""
import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules.chat.conversations import create_course_conversation, create_global_conversation
from app.modules.chat.intent_schema import IntentPayload, TurnDecision, missing_information
from app.modules.chat.migrations import prepare_chat_intent_state
from app.modules.chat.pending_tasks import valid_pending, next_pending, start_request, MAX_CLARIFICATIONS
from app.modules.chat.sending import send_message
from app.modules.chat.turn_intents import resolve_turn_intent, validate_continuation
from app.shared.models import User, Course, Lesson, ChatMessage, ChatConversation, AgentAction, now_utc


def decision(intent=None, *, relation="new", task_id=None, clarification=None, date_source=None):
    return TurnDecision(relation=relation, task_id=task_id,
        intent=IntentPayload.model_validate(intent or {}), clarification=clarification, date_source=date_source)


def call(name, args, identity):
    return {"role": "assistant", "tool_calls": [{"id": identity, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}


DONE = {"content": '{"claims":[],"outcome":"actions_completed"}'}


class TurnContractTest(unittest.TestCase):
    def test_existing_entity_conflict_is_replanned_not_automatically_rewritten(self):
        creation = decision({"create_lesson": {"course": "计算机", "title": "第一讲", "lesson_date": "明天"}}, date_source="明天")
        modification = decision({"edit": {"kind": "lesson", "target": "第一讲", "fields": {"lesson_date": "明天"}}}, date_source="明天")
        with patch("app.modules.agent.completion.complete", side_effect=[
                {"content": creation.model_dump_json()}, {"content": modification.model_dump_json()}]) as model:
            result = resolve_turn_intent("第一讲就排在明天吧", bound_course="计算机",
                entities={"lessons": ["第一讲"]}, reference_day=date(2026, 11, 1))
        self.assertIsNone(result.intent.create_lesson)
        self.assertEqual(result.intent.edit.fields["lesson_date"], "2026-11-02")
        self.assertEqual(model.call_count, 2)

    def test_explicit_duplicate_creation_does_not_gain_edit_permission(self):
        creation = decision({"create_lesson": {"course": "计算机", "title": "第一讲"}})
        refusal = decision({"issue": "已有同名课次，请提供其他标题？"})
        with patch("app.modules.agent.completion.complete", side_effect=[
                {"content": creation.model_dump_json()}, {"content": refusal.model_dump_json()}]):
            result = resolve_turn_intent("另外新建一节同名的第一讲", bound_course="计算机", entities={"lessons": ["第一讲"]})
        self.assertFalse(result.intent.write_keys())
        with patch("app.modules.agent.completion.complete", return_value={"content": creation.model_dump_json()}) as model:
            with self.assertRaises(HTTPException):
                resolve_turn_intent("再建第一讲", bound_course="计算机", entities={"lessons": ["第一讲"]})
        self.assertEqual(model.call_count, 2)

    def test_every_natural_expression_uses_semantic_model_without_keyword_gate(self):
        intent = {"quiz": {"mode": "quiz", "count": 3, "question_type": "true_false"}}
        for prompt in ("考考我，三道判断就好", "安排三个对错题", "用对错题检验下，来三道"):
            with self.subTest(prompt=prompt), patch("app.modules.agent.completion.complete", return_value={
                    "content": decision(intent).model_dump_json()}) as model:
                result = resolve_turn_intent(prompt)
                self.assertEqual(result.intent.quiz.count, 3)
                model.assert_called_once()
                self.assertEqual(json.loads(model.call_args.args[0][1]["content"])["current_request"], prompt)

    def test_relative_date_uses_explicit_reference(self):
        data = decision({"edit": {"kind": "lesson", "target": "第一讲", "fields": {"lesson_date": "明天"}}}, date_source="明天")
        with patch("app.modules.agent.completion.complete", return_value={"content": data.model_dump_json()}):
            result = resolve_turn_intent("把日期挪到明天", reference_day=date(2026, 11, 1))
        self.assertEqual(result.intent.edit.fields["lesson_date"], "2026-11-02")

    def test_model_cannot_invent_year_for_month_day(self):
        data=decision({"edit":{"kind":"lesson","target":"第一讲","fields":{"lesson_date":"2026-11-02"}}},date_source="11月2日")
        with patch("app.modules.agent.completion.complete",return_value={"content":data.model_dump_json()}):
            result=resolve_turn_intent("第一讲日期改为11月2日",reference_day=date(2026,11,1))
        self.assertEqual(result.intent.edit.fields["lesson_date"],"11月2日")
        self.assertIn("年份",result.clarification)

    def test_date_evidence_must_come_from_authorized_input(self):
        data=decision({"edit":{"kind":"lesson","target":"第一讲","fields":{"lesson_date":"2026-11-02"}}},date_source="2026年11月2日")
        with patch("app.modules.agent.completion.complete",return_value={"content":data.model_dump_json()}):
            with self.assertRaises(HTTPException): resolve_turn_intent("改为11月2日")

    def test_only_year_can_complete_the_valid_pending_date(self):
        pending={"id":"p","intent":{"edit":{"kind":"lesson","target":"第一讲","fields":{"lesson_date":"11月2日"}}},
                 "request":"把第一讲挪到11月2日","date_source":"11月2日"}
        data=decision({"edit":{"kind":"lesson","target":"第一讲","fields":{"lesson_date":"2026-11-02"}}},relation="continue",task_id="p",date_source="2026年")
        with patch("app.modules.agent.completion.complete",return_value={"content":data.model_dump_json()}):
            result=resolve_turn_intent("2026年",pending=pending)
        self.assertEqual(result.intent.edit.fields["lesson_date"],"2026-11-02")
        self.assertIsNone(result.clarification)

    def test_closed_historical_commands_are_not_given_to_planner(self):
        history=[{"role":"user","content":"创建操作系统课程"},{"role":"assistant","content":"请给出学期？"},
                 {"role":"user","content":"取消"},{"role":"assistant","content":"已取消"}]
        with patch("app.modules.agent.completion.complete",return_value={"content":decision().model_dump_json()}) as model:
            resolve_turn_intent("操作系统",history)
            payload=json.loads(model.call_args.args[0][1]["content"])
        self.assertNotIn("history",payload)
        self.assertIsNone(payload["pending_task"])
        self.assertNotIn("创建",str(payload))

    def test_optional_fields_cannot_block_a_complete_request(self):
        output=decision({"create_course":{"name":"操作系统"}},clarification="请问是哪个学期？")
        with patch("app.modules.agent.completion.complete",return_value={"content":output.model_dump_json()}):
            result=resolve_turn_intent("操作系统")
        self.assertIsNone(result.clarification)
        self.assertIsNone(result.intent.create_course.semester)

    def test_invalid_output_repairs_once_then_fails_closed(self):
        with patch("app.modules.agent.completion.complete", side_effect=[{"content": "not-json"},
                {"content": decision().model_dump_json()}]) as model:
            self.assertEqual(resolve_turn_intent("查询课程").intent.write_keys(), set())
            self.assertEqual(model.call_count, 2)
        with patch("app.modules.agent.completion.complete", return_value={"content": '{"intent":{"delete_course":{}}}'}) as model:
            with self.assertRaises(HTTPException) as failed:
                resolve_turn_intent("删除课程")
            self.assertEqual(failed.exception.status_code, 502)
            self.assertEqual(model.call_count, 2)

    def test_provider_failure_does_not_fall_back_to_regex_authorization(self):
        with patch("app.modules.agent.completion.complete", side_effect=HTTPException(503, "offline")) as model:
            with self.assertRaises(HTTPException):
                resolve_turn_intent("创建课程操作系统")
            model.assert_called_once()

    def test_continuation_needs_task_identity_and_cannot_expand_actions(self):
        pending = {"id": "p", "intent": {"edit": {"kind": "lesson", "target": "第一讲", "fields": {}}}}
        continued = decision({"edit": {"kind": "lesson", "target": "第一讲", "fields": {"lesson_date": "2026-11-02"}}}, relation="continue", task_id="p")
        validate_continuation(continued, pending)
        for state in (None, pending | {"id": "other"}):
            with self.assertRaises(ValueError): validate_continuation(continued, state)
        with self.assertRaises(ValueError):
            validate_continuation(decision({"create_course": {"name": "新课程"}}, relation="continue", task_id="p"), pending)
        with self.assertRaises(ValueError):
            validate_continuation(continued, pending | {"completed_tools": ["update_lesson"]})

    def test_cancel_cannot_authorize_write_and_incomplete_slots_remain_typed(self):
        with self.assertRaises(ValueError): decision({"create_course": {"name": "新课程"}}, relation="cancel")
        for value in ({"create_course": {}}, {"edit": {"kind": "lesson"}}, {"knowledge": {"title": "CPU"}}):
            self.assertTrue(missing_information(IntentPayload.model_validate(value)))
        self.assertIsNone(missing_information(IntentPayload.model_validate({"create_lesson": {"title": "第一讲"}}), "计算机"))

    def test_unsupported_combinations_and_unknown_fields_are_rejected(self):
        for value in ({"create_course": {"name": "A"}, "edit": {"kind": "course", "target": "B", "fields": {"name": "C"}}},
                      {"edit": {"kind": "course", "fields": {"password": "forbidden"}}},
                      {"create_course": {"name": "A"}, "create_lesson": {"course": "B", "title": "第一讲"}},
                      {"issue": "不支持", "create_course": {"name": "A"}}):
            with self.subTest(value=value), self.assertRaises(ValueError): IntentPayload.model_validate(value)


class SemanticSendingTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id="u", username="owner", password_hash="test-only")); self.db.flush()
        self.db.add(Course(id="c", owner_id="u", name="计算机")); self.db.flush()
        self.db.add(Lesson(id="l", course_id="c", title="第一讲", lesson_date="2026-10-20")); self.db.commit()
        self.chat = create_course_conversation(self.db, "c", "owner")

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def send(self, prompt, request="r"):
        return send_message(self.db, self.chat["id"], "owner", prompt, request)

    def pending(self):
        raw = self.db.get(ChatConversation, self.chat["id"]).pending_task_json
        return json.loads(raw) if raw else None

    def prime(self):
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=decision({
                "edit": {"kind": "lesson", "target": "第一讲", "fields": {"lesson_date": "11月2日"}}}, clarification="请补充日期年份？")):
            self.send("第一讲挪到11月2日", "first")
        self.assertIsNotNone(self.pending())

    @patch("app.modules.agent.loop.complete")
    def test_complete_date_followup_updates_once_and_consumes_pending(self, model):
        self.prime(); task = self.pending()
        model.side_effect = [call("list_lessons", {"course_id": "c"}, "find"),
            call("update_lesson", {"lesson_id": "l", "lesson_date": "2026-11-02"}, "write"), DONE]
        plan = decision({"edit": {"kind": "lesson", "target": "第一讲", "fields": {"lesson_date": "2026-11-02"}}}, relation="continue", task_id=task["id"])
        with patch("app.modules.chat.sending.resolve_turn_intent", return_value=plan) as parser:
            result = self.send("2026年11月2日", "second")
            self.assertEqual(parser.call_args.kwargs["pending"]["id"], task["id"])
            self.assertEqual(self.db.get(Lesson,"l").lesson_date, "2026-11-02")
            self.assertIsNone(self.pending())
            self.assertEqual(self.send("2026年11月2日", "second"), result)
            parser.assert_called_once()
        self.assertEqual(self.db.query(AgentAction).count(), 1)

    def test_expired_foreign_scope_and_non_adjacent_state_cannot_resume(self):
        self.prime(); state=self.pending(); chat=self.db.get(ChatConversation,self.chat["id"])
        self.assertIsNotNone(valid_pending(state,chat,3))
        for bad in (state | {"expires_at":(now_utc()-timedelta(seconds=1)).isoformat()},
                    state | {"scope":state["scope"] | {"user_id":"other"}},
                    state | {"scope":state["scope"] | {"lesson_id":"other"}},
                    state | {"turns":MAX_CLARIFICATIONS+1}):
            self.assertIsNone(valid_pending(bad,chat,3))
        self.assertIsNone(valid_pending(state,chat,5))

    def test_cancel_clears_pending_without_model_tool_loop(self):
        self.prime()
        with patch("app.modules.chat.sending.resolve_turn_intent",return_value=decision(relation="cancel")), patch("app.modules.chat.sending.run_agent") as agent:
            result=self.send("算了，不弄了", "cancel")
            self.assertIn("取消",result["messages"][-1]["content"])
            agent.assert_not_called()
        self.assertIsNone(self.pending())
        self.assertEqual(self.db.get(Lesson,"l").lesson_date,"2026-10-20")

    def test_clarification_budget_expires_without_renewal_or_write(self):
        self.prime()
        first = self.pending()
        for turn in range(MAX_CLARIFICATIONS):
            task = self.pending()
            plan = decision(task["intent"], relation="continue", task_id=task["id"],
                            clarification="请明确年份？")
            with patch("app.modules.chat.sending.resolve_turn_intent", return_value=plan), \
                    patch("app.modules.chat.sending.run_agent") as agent:
                result = self.send("年份还没确定", f"clarify-{turn}")
                agent.assert_not_called()
            if turn < MAX_CLARIFICATIONS - 1:
                self.assertEqual(self.pending()["expires_at"], first["expires_at"])
        self.assertIsNone(self.pending())
        self.assertIn("次数已达到上限", result["messages"][-1]["content"])
        self.assertEqual(self.db.query(AgentAction).count(), 0)

    def test_topic_switch_removes_pending_and_no_old_write_tools(self):
        self.prime()
        with patch("app.modules.chat.sending.resolve_turn_intent",return_value=decision()), patch("app.modules.chat.sending.run_agent",return_value={"answer":"新话题","citations":[],"outcome":"answered","steps":[]}) as agent:
            self.send("先聊聊CPU吧", "switch")
            self.assertFalse(agent.call_args.args[1].actions)
        self.assertIsNone(self.pending())

    def test_short_read_still_uses_semantic_parser_and_never_regex_fallback(self):
        with patch("app.modules.chat.sending.resolve_turn_intent",return_value=decision()), patch("app.modules.chat.sending.run_agent",return_value={"answer":"课程列表","citations":[],"outcome":"answered","steps":[]}) as agent:
            self.send("创建课程只是个例子，解释一下", "quoted")
            self.assertFalse(agent.call_args.args[1].actions)
            self.assertIsNone(agent.call_args.args[1].generate_quiz)

    def test_failed_request_retries_cached_plan_without_second_interpretation(self):
        plan=decision({"edit":{"kind":"lesson","target":"第一讲","fields":{"lesson_date":"2026-11-02"}}})
        with patch("app.modules.chat.sending.resolve_turn_intent",return_value=plan) as parser, patch("app.modules.chat.sending.run_agent",side_effect=[HTTPException(502,"暂时失败"),{"answer":"等待重试","citations":[],"outcome":"needs_input","steps":[]}]):
            with self.assertRaises(HTTPException): self.send("把第一讲挪到明天")
            self.send("把第一讲挪到明天")
            parser.assert_called_once()
        self.assertEqual(self.db.query(ChatMessage).filter_by(role="user").count(),1)


    def test_plan_is_not_saved_if_generation_cancelled_during_parser(self):
        from app.modules.chat.cancellation import stop_generation
        def cancel(*args, **kwargs):
            stop_generation(self.db,self.chat["id"],"owner","r")
            return decision({"create_course":{"name":"不应创建"}})
        with patch("app.modules.chat.sending.resolve_turn_intent",side_effect=cancel), patch("app.modules.chat.sending.run_agent") as agent:
            self.send("建一门不应创建的课程")
            agent.assert_not_called()
        self.assertIsNone(self.pending())

    def test_partial_success_pending_keeps_only_unfinished_action(self):
        self.chat=create_global_conversation(self.db,"owner")
        chat=self.db.get(ChatConversation,self.chat["id"])
        message=ChatMessage(id="m",conversation_id=chat.id,role="user",content="创建课程再添加课次",position=1,request_id="partial")
        self.db.add(message); self.db.flush()
        self.db.add(AgentAction(message_id="m",tool="create_course",arguments_json='{}',result_json='{}')); self.db.commit()
        plan=decision({"create_course":{"name":"操作系统"},"create_lesson":{"course":"操作系统","title":None}})
        result={"outcome":"actions_completed","answer":"课程已创建；请提供课次标题？","clarification":"请提供课次标题？"}
        state=json.loads(next_pending(self.db,chat,message,{"pending":None},plan,result))
        self.assertNotIn("create_course",state["intent"])
        self.assertEqual(state["intent"]["create_lesson"]["course"],"操作系统")
        self.assertEqual(state["completed_tools"],["create_course"])

    def test_entity_hints_are_scoped_and_bounded(self):
        from app.modules.chat.intent_entities import intent_entities, ENTITY_LIMIT
        self.db.add(User(id="v",username="other",password_hash="test-only"));self.db.flush()
        self.db.add(Course(id="private",owner_id="v",name="不应可见"));self.db.flush()
        self.db.add_all([Lesson(id=f"extra-{i}",course_id="c",title=f"课次{i}") for i in range(ENTITY_LIMIT+1)])
        self.db.commit()
        hints=intent_entities(self.db,"u","c")
        self.assertEqual(hints["courses"],["计算机"])
        self.assertEqual(len(hints["lessons"]),ENTITY_LIMIT)
        self.assertTrue(hints["lessons_truncated"])
        self.assertEqual(intent_entities(self.db,"u","c","l")["lessons"],["第一讲"])
        self.assertNotIn("不应可见",str(intent_entities(self.db,"u")))

    def test_quiz_tool_cannot_change_explicit_count_type_or_lesson(self):
        from app.modules.agent.schemas import QuizArguments
        from app.modules.chat.quiz_actions import generate_for_message
        chat=self.db.get(ChatConversation,self.chat["id"]);chat.generation_token="token"
        self.db.add(ChatMessage(id="quiz-request",conversation_id=chat.id,role="user",content="出题",request_id="quiz",position=1,status="pending"));self.db.commit()
        variants=[{"count":5,"question_type":"true_false","lesson_ids":["l"]},
                  {"count":3,"question_type":"single_choice","lesson_ids":["l"]},
                  {"count":3,"question_type":"true_false"}]
        requested={"count":3,"question_type":"true_false","course":"计算机","lessons":["第一讲"]}
        with patch("app.modules.chat.quiz_actions.generate_quiz") as generate:
            for values in variants:
                with self.subTest(values=values),self.assertRaises(HTTPException):
                    generate_for_message(self.db,chat.id,"owner","quiz-request","token",QuizArguments(course_id="c",**values),requested=requested)
            generate.assert_not_called()


class IntentMigrationTest(unittest.TestCase):
    def test_existing_database_migration_is_idempotent_and_preserves_rows(self):
        engine=create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE chat_conversations (id TEXT PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE chat_messages (id TEXT PRIMARY KEY, content TEXT)"))
            connection.execute(text("INSERT INTO chat_messages VALUES ('m','原有消息')"))
        prepare_chat_intent_state(engine); prepare_chat_intent_state(engine)
        self.assertIn("pending_task_json",{c["name"] for c in inspect(engine).get_columns("chat_conversations")})
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT content, intent_state_json FROM chat_messages")).one(),("原有消息",None))
        engine.dispose()

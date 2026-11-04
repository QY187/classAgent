"""组合已核验的读取结果；每类业务保持自己的查询和权限校验。"""
import re
from fastapi import HTTPException
from ...core.telemetry import traced
from .goals import select_outputs, requested_outputs, incomplete_notice, requirements_for, selection_issues


@traced("answer.compose")
def compose_answer(db, context, payload, evidence, steps):
    payload = select_outputs(context, payload)
    parts, citations, unavailable = {}, [], []
    completed = set()
    invalid = selection_issues(db, context, payload, evidence)
    compact = requested_outputs(context) is not None

    def append_result(label, reader, output):
        if output in invalid:
            return
        try:
            result = reader()
        except HTTPException as exc:
            if exc.status_code not in {400, 404, 409, 502, 503, 504}:
                raise
            unavailable.append(f"{label}当前无法核对，请检查资料范围或稍后重试。")
            return
        if isinstance(result, str):
            if result:
                parts[output] = result
                completed.add(output)
        else:
            parts[output] = result["answer"]
            citations.extend(result["citations"])
            if result["citations"]:
                completed.add(output)

    # 先回答“在哪、是什么”，再给相关业务记录；引用编号与最终展示顺序一致。
    if compact and payload.get("locations") is not None:
        append_result("内容位置", lambda: evidence.location_answer(
            db, context, payload["locations"], citation_offset=len(citations),
            concise=context.action_hints.get("response_contract") is not None), "locations")
    if compact and payload["claims"]:
        append_result("课堂结论", lambda: evidence.answer(
            db, context, payload["claims"], citation_offset=len(citations)), "claims")
    if payload.get("catalog") is not None:
        append_result("课程与课次目录", lambda: "\n".join(evidence.catalog_answer(db, context, payload["catalog"])), "catalog")
    if payload.get("progress") is not None:
        views = requirements_for(context, "progress")
        view = "missing_summaries" if views and all(item["view"] == "missing_summaries" for item in views) else "progress"
        append_result("课程进度", lambda: evidence.progress.answer(db, context, payload["progress"], view=view), "progress")
    if payload.get("quiz_results") is not None:
        append_result("小测成绩", lambda: evidence.quiz_results.answer(
            db, context, payload["quiz_results"], citation_offset=len(citations)), "quiz_results")
    if payload.get("learning") is not None:
        append_result("学习记录", lambda: evidence.learning.answer(db, context, payload["learning"], compact=compact), "learning")
    if payload.get("workflow") is not None:
        append_result("处理与小测记录", lambda: evidence.workflow.answer(db, context, payload["workflow"]), "workflow")
    if not compact and payload.get("locations") is not None:
        append_result("内容位置", lambda: evidence.location_answer(
            db, context, payload["locations"], citation_offset=len(citations)), "locations")
    if not compact and payload["claims"]:
        append_result("课堂结论", lambda: evidence.answer(
            db, context, payload["claims"], citation_offset=len(citations)), "claims")
    verified_business = bool(set(parts) - {"claims", "locations"})
    if parts or unavailable:
        missing = [key for key in (requested_outputs(context) or ()) if key not in completed]
        # 有字段却未取得有效结果也不是完成；查询的空清单仍由业务服务核验。
        if missing:
            unavailable.append(incomplete_notice(missing))
        titles = {"locations": "内容出处", "claims": "课堂说明", "learning": "学习记录", "progress": "纪要与进度",
                  "workflow": "处理记录", "catalog": "课程与课次", "quiz_results": "小测结果"}
        order = ([key for key in ("locations", "claims", "learning", "progress", "quiz_results", "workflow", "catalog") if key in parts]
                 if compact else list(parts))
        blocks = [f"**{titles[key]}**\n\n{parts[key]}" if compact and len(parts) > 1 else parts[key] for key in order]
        return {"answer": "\n\n".join(blocks + unavailable), "citations": citations,
                "outcome": ("answered" if verified_business or citations else
                            "insufficient_evidence" if parts else "operation_failed"), "steps": steps}
    if payload.get("outcome") == "needs_input":
        return {"answer": payload["question"], "citations": [], "outcome": "needs_input", "steps": steps}
    result = evidence.answer(db, context, [])
    if requested_outputs(context):
        result["answer"] += "\n\n" + incomplete_notice(requested_outputs(context))
    return {**result, "outcome": "insufficient_evidence", "steps": steps}


def requested_query_groups(question):
    groups = set()
    for clause in re.split(r"[，,。；;]|同时|顺便|并且|以及", question):
        if not re.search(r"查询|列出|查看|看看|告诉|哪些|多少|成绩|正确率|进度", clause):
            continue
        if re.search(r"成绩|正确率|作答记录", clause):
            groups.add("quiz_results")
        if re.search(r"待处理|处理阶段|处理进度|失败原因|未作答|还没做|没有做", clause) or ("小测" in clause and not re.search(r"成绩|正确率|作答记录", clause)):
            groups.add("workflow")
        if re.search(r"课程进度|缺少纪要", clause):
            groups.add("progress")
        if re.search(r"知识点|错题", clause):
            groups.add("learning")
    if requested_catalog_kinds(question):
        groups.add("catalog")
    return groups


def requested_catalog_kinds(question):
    kinds = set()
    if not re.search(r"查询|列出|查看|看看|告诉|哪些|有哪些", question):
        return kinds
    if re.search(r"所有课程|全部课程|课程列表|课程目录|课程名称|有哪些课程", question):
        kinds.add("list_courses")
    if re.search(r"所有课次|全部课次|课次列表|课次目录|有哪些课次", question) and not re.search(r"待处理|未完成|没有纪要|缺少纪要", question):
        kinds.add("list_lessons")
    return kinds

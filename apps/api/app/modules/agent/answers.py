"""组合已核验的读取结果；每类业务保持自己的查询和权限校验。"""
import re
from fastapi import HTTPException


def compose_answer(db, context, payload, evidence, steps):
    parts, citations, unavailable = [], [], []

    def append_result(label, reader):
        try:
            result = reader()
        except HTTPException as exc:
            if exc.status_code not in {400, 404, 409, 502, 503, 504}:
                raise
            unavailable.append(f"{label}当前无法核对，请检查资料范围或稍后重试。")
            return
        if isinstance(result, str):
            if result:
                parts.append(result)
        else:
            parts.append(result["answer"])
            citations.extend(result["citations"])

    if payload.get("catalog") is not None:
        append_result("课程与课次目录", lambda: "\n".join(evidence.catalog_answer(db, context, payload["catalog"])))
    if payload.get("progress") is not None:
        append_result("课程进度", lambda: evidence.progress.answer(db, context, payload["progress"]))
    if payload.get("quiz_results") is not None:
        append_result("小测成绩", lambda: evidence.quiz_results.answer(
            db, context, payload["quiz_results"], citation_offset=len(citations)))
    if payload.get("learning") is not None:
        append_result("学习记录", lambda: evidence.learning.answer(db, context, payload["learning"]))
    if payload.get("workflow") is not None:
        append_result("处理与小测记录", lambda: evidence.workflow.answer(db, context, payload["workflow"]))
    verified_business = bool(parts)
    if payload["claims"]:
        append_result("课堂结论", lambda: evidence.answer(
            db, context, payload["claims"], citation_offset=len(citations)))
    if parts or unavailable:
        return {"answer": "\n\n".join(parts + unavailable), "citations": citations,
                "outcome": ("answered" if verified_business or citations else
                            "insufficient_evidence" if parts else "operation_failed"), "steps": steps}
    if payload.get("outcome") == "needs_input":
        return {"answer": payload["question"], "citations": [], "outcome": "needs_input", "steps": steps}
    result = evidence.answer(db, context, [])
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

"""组合已核验的读取结果；每类业务保持自己的查询和权限校验。"""
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

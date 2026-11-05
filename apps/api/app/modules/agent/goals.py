"""最终交付与内部读取分离；目标只约束展示，不能授权写入或放宽证据校验。"""

OUTPUT_LABELS = {"claims": "课堂内容解答", "locations": "课程课次位置", "catalog": "课程课次目录",
                 "learning": "知识点或错题记录", "progress": "课程进度", "quiz_results": "小测成绩与作答",
                 "workflow": "处理或小测记录", "assistant": "助手介绍与使用帮助"}


def requested_outputs(context):
    contract = context.action_hints.get("response_contract")
    if contract is not None:
        return tuple(contract["outputs"])
    # 兼容上一版已经持久化的位置请求快照。
    if context.action_hints.get("answer_mode") == "source_location":
        return ("locations",)
    return None


def select_outputs(context, payload):
    outputs = requested_outputs(context)
    if outputs is None:
        return payload
    selected = {key: value for key, value in payload.items() if key not in OUTPUT_LABELS or key in outputs}
    selected.setdefault("claims", [])
    return selected


def missing_outputs(context, payload):
    outputs = requested_outputs(context)
    if outputs is None or payload.get("outcome") == "needs_input":
        return []
    return [key for key in outputs if not payload.get(key)]


def requirements_for(context, output):
    return [item for item in context.action_hints.get("response_contract", {}).get("requirements", [])
            if item["output"] == output]


def selection_issues(db, context, payload, store):
    """验证最终选择的查询满足本轮筛选条件；辅助查询不能冒充交付。"""
    from .tools import check_lesson
    from .claim_validation import verified_claims
    current, lessons = store.current_evidence(db, context)
    located = {lessons[current[key].lesson_id].course_id
               for key in (payload.get("locations") or {}).get("source_ids", []) if key in current}
    issues = {}
    for output in ("learning", "progress"):
        required = requirements_for(context, output)
        selection = payload.get(output)
        if not required or selection is None:
            continue
        selected, matched = [], set()
        for key in selection.get("query_ids", []):
            entry = getattr(store, output).queries.get(key)
            if entry is None:
                issues[output] = "最终查询编号必须来自本轮实际读取。"
                continue
            name, args = entry if output == "learning" else ("get_course_progress", entry)
            course_id = args.course_id or context.course_id
            if output == "learning" and args.lesson_id:
                course_id = check_lesson(db, context, args.lesson_id).course_id
            valid = []
            for index, item in enumerate(required):
                tool = {"knowledge_points": "list_knowledge_points", "wrong_questions": "list_wrong_questions",
                        "progress": "get_course_progress", "missing_summaries": "get_course_progress"}[item["view"]]
                if name != tool or (item.get("status") is not None and args.status != item["status"]):
                    continue
                if item.get("query") and args.query.casefold() != item["query"].casefold():
                    continue
                if item.get("scope") == "located_courses" and (not located or course_id not in located):
                    continue
                valid.append(index)
                matched.add((index, course_id))
            selected.append(bool(valid))
        covered = all((all((index, course) in matched for course in located) and bool(located))
                      if item.get("scope") == "located_courses" else any(index == match[0] for match in matched)
                      for index, item in enumerate(required))
        if not selected or not all(selected) or not covered:
            issues[output] = ("最终查询必须满足response_contract.requirements的状态、主题和课程范围；"
                              "先定位再查询相应课程，不能选择内部的全部状态/全课程查询代替。"
                              "缺少可用纪要必须使用get_course_progress，不用一般待处理查询代替。")
    if requested_outputs(context) is not None and payload.get("claims"):
        if any(not verified_claims([claim], current, fallback=False) for claim in payload["claims"]):
            issues["claims"] = ("课堂结论必须选取本轮evidence中对应片段的完整原文句子，保持否定、条件、数字和单位。"
                                "父块首段的evidence_id不能代表后续正文；请使用evidence数组中实际支持该结论的编号。"
                                "不得用标题替代解释；原文截断时继续读取get_transcript。")
    return issues


def incomplete_notice(missing):
    return "尚未完成的回答：" + "、".join(OUTPUT_LABELS[key] for key in missing) + "。本次结果仅覆盖已核验的部分。"


GOAL_INSTRUCTION = """围绕用户要获得的结果执行，不以调用过某个工具作为任务完成标志。
response_contract.goal 是本次交付目标；outputs 是用户实际要展示的结果类别。内部定位、核对、选题用到的查询不是额外展示要求。
requirements明确学习/进度查询的状态、主题、视图与范围，必须逐项遵循。scope=located_courses时先核实内容位置，再以匹配课程ID查询。只问需要复习就用status=review，不展示all候选；缺少可用纪要查询get_course_progress，最终返回progress。
每轮根据工具返回的数据判断下一步：范围内可继续查询时不要过早澄清；无匹配时调整关键词、查询来源或分页；权限限制不能通过换用户或越过绑定范围规避。
最终保留outputs中的每一项：claims课堂解答、locations内容位置、catalog目录、learning学习记录、progress进度、quiz_results成绩、workflow处理记录、assistant助手介绍与使用帮助。
必须结合真实工具结果及来源判断相关性，不能把某类工具已调用等同于该项已经回答。没有有效依据时如实说明不足，不编造结果以凑齐字段。
已成功写入不重复执行；部分完成时保留有效结果，缺失部分明确说明。不要附加用户没要求的状态、目录或统计。
原文工具返回的evidence数组把文字和引用编号逐段对应；snippet只是上下文。解释时选择直接回答用户问题的句子及例子，不能引用标题代替性质说明，不能重复同一句充数。
"""

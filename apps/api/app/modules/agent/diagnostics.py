"""只根据本轮工具记录及重新核对的本人可见状态解释未完成原因。"""
from fastapi import HTTPException
from sqlalchemy import select, func
from ...shared.models import Lesson, TranscriptSegment, AudioFile, LessonSummary, CourseMaterial, MaterialProcessing, ProcessingJob
from .tools import check_course, check_lesson
from ...core.chat_failures import REASONS

LABELS = {"list_courses":"查找课程", "list_lessons":"查找课次", "search_course":"检索课堂资料", "get_transcript":"读取文字记录",
          "get_summary":"读取纪要", "list_materials":"查询课件", "get_material_content":"读取课件", "get_course_progress":"核对课程资料状态", "generate_quiz":"生成小测", "generate_practice_quiz":"生成复习练习",
          "create_course":"创建课程", "create_lesson":"添加课次", "update_course":"修改课程", "update_lesson":"修改课次",
          "update_knowledge_status":"修改知识点状态", "retry_transcription":"重试转写"}

def tool_problem(name, error):
    label = LABELS.get(name, "执行本次操作")
    code = error.get("code", "execution_failed")
    message = error.get("message", "")
    if code == "not_found":
        return f"{label}时，目标资料不存在、已删除或不在当前可访问范围内。请确认课程或课次，或刷新资料后重试。"
    if code in {"forbidden", "unauthenticated"}:
        return f"{label}未完成：当前登录或访问权限不满足要求。请重新登录，或进入有权限的课程对话。"
    if code in {"invalid_arguments", "invalid_context", "unknown_tool"}:
        return f"{label}未执行：本轮调用的参数或范围不符合要求。请明确目标课程、课次和操作要求后重试；这不是资料为空。"
    if code == "state_not_ready":
        return f"{label}未完成：{message}。请查看对应资料的处理状态，满足读取条件后再查询。".replace("。。", "。")
    if code == "source_changed":
        return f"{label}未完成：资料或状态在查询期间发生变化。请刷新对应资料后重新查询，本次不使用过期结果。"
    if code == "generation_failed":
        return f"{label}未完成：{message}".rstrip("。") + "。"
    if code == "action_rejected":
        return f"{label}未完成：{message}。请按上述原因确认目标和参数后再试。".replace("。。", "。")
    if code in REASONS and code != "internal_error":
        return f"{label}未完成：{REASONS[code][1]} 本次无法据此判断资料是否存在。"
    return f"{label}时发生服务或执行异常，本次未能取得有效结果；不能把这次失败当成没有资料。请稍后重试，持续失败时可查看请求执行详情。"

def diagnostic_result(code, text, steps, failed=False):
    return {"answer":text, "citations":[], "outcome":"operation_failed" if failed else "insufficient_evidence", "steps":steps,
            "diagnostic":True, "diagnostic_code":code,
            "answer_materials":[{"id":"diagnostic", "content":text, "citation_ids":[]}]}

def explain_missing(db, context, evidence, steps):
    observations = evidence.observations
    if not observations:
        return diagnostic_result("read_not_attempted", "本轮尚未完成有效的资料读取，因此暂时无法可靠回答；这不代表课程没有资料。可以重试这条问题，或指定要读取的课次、课件。", steps)
    # 后续同工具成功时视为已恢复，不能用旧错误覆盖新的查询结果。
    last = {}
    for item in observations:
        last[(item["tool"], item["scope"])] = item
    errors = [item for item in last.values() if not item["ok"]]
    if errors:
        descriptions = list(dict.fromkeys(tool_problem(item["tool"], item["error"]) for item in errors))
        return diagnostic_result("tool_failed", "\n\n".join(descriptions), steps, failed=True)
    # 名称检索为空只代表本次条件，不等价于账号没有课程。
    for name, args, data in reversed(evidence.catalog_reads):
        if name in {"list_courses", "list_lessons"} and data.get("total") == 0 and not args.get("offset", 0):
            label = "课程" if name == "list_courses" else "课次"
            query = args.get("query")
            text = f"按本次名称条件“{query}”没有找到匹配的{label}" if query else f"当前查询范围内没有可见的{label}"
            return diagnostic_result("target_not_found", text + "，因此还无法读取对应内容。请确认名称，或先查看课程与课次列表。", steps)
    if evidence.entries:
        return diagnostic_result("read_evidence_incomplete", "本轮已经读取到部分原文，但尚未形成足以回答本次问题的完整、可核验的课堂内容解答；不能据此认定课程没有资料。可以缩小问题范围，或继续要求补全解释。", steps)
    scopes = {item["course_id"] for item in observations if item["ok"] and item.get("course_id")}
    course_id = context.course_id or (next(iter(scopes)) if len(scopes) == 1 else None)
    if course_id is None and len(evidence.course_ids) == 1:
        course_id = next(iter(evidence.course_ids))
    if course_id is None:
        return diagnostic_result("scope_unresolved", "本次尚未唯一定位到要回答的课程或课次，不能据此判断某门课程没有资料。请明确课程名称或进入对应课程对话后提问。", steps)
    try:
        course = check_course(db, context, course_id)
        lesson = check_lesson(db, context, context.lesson_id) if context.lesson_id else None
    except HTTPException:
        return diagnostic_result("scope_unavailable", "本次定位的课程或课次已不可访问，无法继续核对资料。请刷新列表并选择当前有权限的目标。", steps, failed=True)
    ids = [lesson.id] if lesson else list(db.scalars(select(Lesson.id).where(Lesson.course_id == course.id)))
    name = f"《{course.name}》" + (f"的“{lesson.title}”课次" if lesson else "课程")
    def count(model):
        return db.scalar(select(func.count()).select_from(model).where(model.lesson_id.in_(ids))) or 0
    preference = context.action_hints.get("source_type", "all")
    segments = count(TranscriptSegment) if preference != "material" else 0
    audio = count(AudioFile) if preference != "material" else 0
    summaries = db.scalar(select(func.count()).select_from(LessonSummary).where(LessonSummary.lesson_id.in_(ids),
        LessonSummary.status.in_(["completed", "edited"]), LessonSummary.content.is_not(None), func.trim(LessonSummary.content) != "")) or 0
    material_query = select(CourseMaterial.id).where(CourseMaterial.course_id == course.id)
    if lesson:
        material_query = material_query.where((CourseMaterial.lesson_id == lesson.id) | CourseMaterial.lesson_id.is_(None))
    material_ids = list(db.scalars(material_query)) if preference != "transcript" else []
    if preference == "material" and not material_ids:
        return diagnostic_result("no_materials", f"{name}当前没有可见的上传课件。本次要求只查看课件，因此不能用录音内容替代；请上传文字型课件或调整资料来源后再问。", steps)
    if not segments and not material_ids and not audio and (not summaries or preference == "material"):
        text = f"{name}目前" + ("没有课次，也没有可见的课程公共课件" if not ids else f"有 {len(ids)} 个可见课次，但没有音频、文字记录或上传课件，也没有可用的已保存纪要")
        if preference == "transcript":
            text = f"{name}在本次限定的录音资料范围内没有音频或文字记录，不能用其他课件替代"
        next_step = "补充音频或文字记录" if preference == "transcript" else "录音、上传音频或课件"
        return diagnostic_result("empty_scope", text + f"，暂时无法概括讲授内容。可以先{next_step}，再根据处理后的资料提问。", steps)
    # 音频状态只采用各课次最近一次任务，不把旧失败说成当前失败。
    jobs = list(db.scalars(select(ProcessingJob).where(ProcessingJob.lesson_id.in_(ids)).order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())))
    latest = {}
    for job in jobs: latest.setdefault(job.lesson_id, job.stage)
    if not segments and not material_ids and audio:
        active = sum(stage in {"queued", "transcribing"} for stage in latest.values())
        failed = sum(stage == "failed" for stage in latest.values())
        states_text = ([f"{active} 个课次的最新转写任务仍在排队或处理中"] if active else []) + ([f"{failed} 个课次的最新转写任务失败"] if failed else [])
        state = "；".join(states_text) if states_text else "目前尚未取得可用文字记录，未确认到仍在运行的转写任务"
        return diagnostic_result("transcript_pending" if active else "transcript_failed" if failed else "transcript_missing",
            f"{name}已有 {audio} 份音频，但还没有文字记录；{state}。请在课次处理详情中核对状态；处理中可等待，失败后可查看原因并明确重试。", steps)
    states = list(db.scalars(select(MaterialProcessing).where(MaterialProcessing.material_id.in_(material_ids)))) if material_ids else []
    readable = sum(bool(state.active_version) for state in states)
    if material_ids and not readable and not segments:
        active = sum(state.status in {"queued", "processing", "indexing"} for state in states)
        failed = sum(state.status == "failed" for state in states)
        states_text = ([f"{active} 份仍在等待、解析或建立索引"] if active else []) + ([f"{failed} 份处理失败"] if failed else [])
        status = "、".join(states_text) if states_text else "还没有可用的解析版本"
        return diagnostic_result("materials_unready", f"{name}已有 {len(material_ids)} 份课件，但{status}，本次还不能读取其正文。请在课件处理详情中核对状态，处理完成或重试成功后再问。", steps)
    if any(item["ok"] and item.get("offset", 0) > 0 and item.get("item_count") == 0 for item in observations):
        return diagnostic_result("page_empty", f"{name}已有资料，但本次分页读取没有返回记录，不能据此认定整门课程没有内容。可以从开头重新读取，或指定课次、课件后再查询。", steps)
    searched = any(item["tool"] == "search_course" and item["ok"] for item in observations)
    if summaries and not segments and not material_ids and not audio:
        return diagnostic_result("summary_only", f"{name}有已保存纪要，但当前没有录音文字记录或可读课件原文，不能仅凭纪要作为课堂结论的原文依据。请补充原始音频、文字记录或课件后再问。", steps)
    if searched:
        return diagnostic_result("search_no_evidence", f"{name}已有已保存的资料，但本次检索没有取得足够的可核验内容；这不代表课程没有资料或老师没有讲过。可以指定课次、课件或更明确的主题关键词后继续查询。", steps)
    return diagnostic_result("content_not_read", f"已定位到{name}，但本轮还没有读取到足够的正文依据，暂不能可靠概括内容。请指定要查看的课次或课件；不能仅凭名称和目录推断课程讲授内容。", steps)

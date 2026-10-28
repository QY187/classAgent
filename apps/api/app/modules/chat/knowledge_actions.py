"""知识点状态只由当前用户的明确命令改变；名称与状态双重校验。"""
import re
from fastapi import HTTPException
from sqlalchemy import select
from ...shared.models import ReviewCard
from ..review_cards import service as cards
from ..review_cards.schemas import CardReview
from ..agent.learning import CARD_STATUSES
from .course_actions import explicit_request, clean_name
from .intents import follows_clarification, request_text, clarification_origin, is_cancellation
from .action_records import perform_for_message
from .access import owned_course, owned_lesson


def _status_target(question):
    match = re.search(r"(?:把|将)(.{1,250}?)(?:标记|设置|设定|改)(?:为|成)", question)
    return clean_name(match[1]) if match else None


def status_request(question, history=None):
    if is_cancellation(question):
        affirmative = affirmative_status_instruction(question)
        if not affirmative:
            return None
        question = affirmative
    if not explicit_request(question):
        if not follows_clarification(question, history):
            return None
        previous = clarification_origin(question, history) or ""
        target = _status_target(previous)
        answer = question.strip().rstrip("？?。！!").strip()
        if not target or answer not in CARD_STATUSES.values():
            return None
        question = f"把{target}标记为{answer}"
    question = request_text(question)
    prefix = r"^(?:请|帮我|给我|麻烦你|麻烦|然后|再|你|\s)*"
    patterns = (prefix + r"(?:把|将)(.{1,250}?)(?:标记|设置|设定|改|设)(?:为|成)(未学习|需要复习|已掌握)(?:吧|一下|[！!\s])*$",
                prefix + r"(?:标记|设置|设)(.{1,250}?)(?:为|成)(未学习|需要复习|已掌握)(?:吧|一下|[！!\s])*$")
    for clause in re.split(r"[，,。；;\n]", question):
        for pattern in patterns:
            match = re.match(pattern, clause.strip())
            if match:
                title = clean_name(match[1]).removesuffix("知识点").strip()
                if not title or re.search(r"全部|所有|这些|它们", title):
                    return None
                return {"title": title, "status": next(key for key, label in CARD_STATUSES.items() if label == match[2])}
    answer = question.strip().rstrip("？?。！!").strip()
    if follows_clarification(question, history) and answer in CARD_STATUSES.values():
        previous = clarification_origin(question, history) or ""
        target = _status_target(previous)
        if target and status_request(previous) is None:
            return status_request(f"把{target}标记为{answer}")
    return None


def affirmative_status_instruction(question):
    # 仅允许独立、完整的肯定指令；全局取消、咨询、引用和同目标冲突仍不授权。
    if re.search(r"老师|原文|资料|引用|假设|如果|示例|举例|怎么|如何|能否|[？?]", question):
        return None
    clauses = [clause.strip() for clause in re.split(r"[，,。；;\n]", question) if clause.strip()]
    negatives = [clause for clause in clauses if is_cancellation(clause)]
    targets = []
    for clause in negatives:
        match = re.fullmatch(r"(?:请)?不要(?:修改|标记|设置|把|将)(.+)", clause)
        if not match:
            return None
        target = _status_target(clause) or match[1].removesuffix("的状态").strip()
        if not target or re.search(r"全部|所有|任何|这些|它们", target):
            return None
        targets.append(target)
    positives = [(clause, status_request(clause)) for clause in clauses if not is_cancellation(clause)]
    positives = [(clause,intent) for clause,intent in positives if intent]
    if len(positives) != 1 or not targets:
        return None
    clause, intent = positives[0]
    if any(target in intent["title"] or intent["title"] in target for target in targets):
        return None
    return clause


def status_request_issue(question):
    requests = [status_request(clause) for clause in re.split(r"[，,。；;\n]|(?=再(?:把|将))", question)]
    targets = {(item["title"], item["status"]) for item in requests if item}
    if is_cancellation(question) and targets and not affirmative_status_instruction(question):
        return "这条指令包含取消、范围不明确或相互冲突的修改要求。请重新明确要修改的单个知识点及状态；当前未执行修改。"
    if len(targets) > 1:
        return "当前每条问题只能修改一个知识点。请明确选择其中一个，或分别发送两条修改指令。"
    return ""


def candidate_cards(db, username, scope, requested):
    rows = []
    for row in cards.list_cards(db, username):
        if scope and row["course_id"] != scope:
            continue
        lesson = owned_lesson(db, row["lesson_id"], username)
        if lesson.course_id != row["course_id"]:
            continue
        title = requested
        named = re.match(r"^(.{1,200}?)课程(?:中|里|下)?(?:的)?(.+)$", title)
        if named:
            if clean_name(named[1]) != row["course_name"] and not (scope and clean_name(named[1]) in {"当前", "这门"}):
                continue
            title = named[2]
        if "的" in title and title.startswith(row["lesson_title"] + "的"):
            title = title[len(row["lesson_title"]) + 1:]
        if title.casefold() == row["title"].casefold() or title.casefold() in row["title"].casefold():
            rows.append((row, title.casefold() == row["title"].casefold()))
    exact = [row for row, match in rows if match]
    return exact or [row for row, _ in rows]


def status_verification_hint(db, username, scope, question, history):
    # 只产生读取提示；不恢复历史写权限，也不把历史回执当作当前状态。
    if not re.fullmatch(r"(?:请问)?(?:刚才|刚刚|之前).{0,12}(?:成功|完成)(?:了)?(?:吗|么)?[？?。!！ ]*", question.strip()):
        return {}
    previous = next((item.get("content", "") for item in reversed(history or []) if item.get("role") == "user"), "")
    intent = status_request(previous)
    if not intent:
        return {}
    try:
        targets = candidate_cards(db, username, scope, intent["title"])
    except HTTPException:
        return {}
    if len(targets) == 1:
        return {"knowledge_point_id":targets[0]["id"]}
    return {"ambiguous":True}


def actions_for_message(db, conversation_id, username, message_id, token, question, history=None, semantic=None):
    raw_question = question
    if semantic is None and status_request_issue(question):
        return {}
    intent = semantic.get("knowledge") if semantic is not None else status_request(question, history)
    if not intent:
        return {}
    def update(args):
        def validate(db, conversation, message, previous):
            if message.content != raw_question or args.status != intent["status"]:
                raise HTTPException(400, "只按你明确指定的状态修改知识点")
            scope = conversation.course_id or (owned_lesson(db, conversation.lesson_id, username).course_id if conversation.lesson_id else None)
            matches = candidate_cards(db, username, scope, intent["title"])
            if conversation.lesson_id:
                matches = [row for row in matches if row["lesson_id"] == conversation.lesson_id]
            if not matches:
                raise HTTPException(400, "没有找到对应知识点，请核对名称和课程范围")
            if len(matches) != 1:
                raise HTTPException(400, "找到多个同名知识点，请明确课程或课次后再标记")
            if matches[0]["id"] != args.knowledge_point_id:
                raise HTTPException(400, "不能修改指令目标以外的知识点")
            row = matches[0]
            owned_course(db, row["course_id"], username, lock=True)
            card = db.scalar(select(ReviewCard).where(ReviewCard.id == args.knowledge_point_id)
                             .with_for_update().execution_options(populate_existing=True))
            if card is None or card.course_id != owned_lesson(db, card.lesson_id, username).course_id:
                raise HTTPException(404, "知识点不存在")
            if previous and card.status != args.status:
                raise HTTPException(409, "该请求已执行后状态再次变化，请发送新的修改指令")
        def write(db):
            card = db.scalar(select(ReviewCard).where(ReviewCard.id == args.knowledge_point_id))
            old = card.status
            if old != args.status:
                result = cards.review_card(db, card.id, CardReview(status=args.status), username, commit=False)
            else:
                result = cards.serialize(card)
            label = CARD_STATUSES[args.status]
            text = f"已将知识点“{result['title']}”标记为{label}。" if old != args.status else f"知识点“{result['title']}”已经是{label}，无需修改。"
            return {"kind": "action", "operation": "update_knowledge_status", "target": "knowledge_point",
                    "id": result["id"], "title": result["title"], "course_id": result["course_id"],
                    "lesson_id": result["lesson_id"], "old_status": old, "status": args.status, "message": text}
        return perform_for_message(db, conversation_id, username, message_id, token, "update_knowledge_status", args.model_dump(), write, validate)
    return {"update_knowledge_status": update}


def visible_action(db, result, username):
    card = db.scalar(select(ReviewCard).where(ReviewCard.id == result["id"]))
    if card is None:
        return None
    try:
        lesson = owned_lesson(db, card.lesson_id, username)
        return result if card.course_id == lesson.course_id == result["course_id"] else None
    except HTTPException:
        return None

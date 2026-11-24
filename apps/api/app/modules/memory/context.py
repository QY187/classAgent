"""有界历史上下文；按模型无关的保守近似分配预算，实际用量仍由供应商计量。"""
import json
import re
from collections import defaultdict
from sqlalchemy import select
from ...shared.models import ChatMessage, ConversationMemorySummary

# 敏感消息整条排除，避免只遮住前缀却留下口令；原消息不在此修改。
MEMORY_COMMAND = re.compile(r"^(全局记住|记住|忘记|修改记忆)[：:]")

SECRET = re.compile(r"密码|口令|验证码|api[_ -]?key|authorization|bearer\s|cookie|token\s*[:=]|secret[_ -]?key", re.I)


def safe_text(text):
    return "[含凭据的信息不用于记忆]" if SECRET.search(text) else text


def cost(text):
    # 中文每字按2、其余连续文本每3个UTF-8字节按1估算；不是特定模型的精确分词。
    chunks=re.findall(r"[\u2e80-\uffff]|[^\u2e80-\uffff]+",text)
    return sum(2 if len(chunk)==1 and ord(chunk)>=0x2e80 else (len(chunk.encode("utf-8"))+2)//3 for chunk in chunks)+32


class MemoryContext(list):
    def __init__(self, rows=(), references=()):
        super().__init__(rows)
        self.references = list(references)


def completed_pairs(db, conversation_id, before_position, *, after_position=-1, limit=200):
    query=select(ChatMessage).where(ChatMessage.conversation_id == conversation_id,
        ChatMessage.position > after_position, ChatMessage.position < before_position, ChatMessage.status == "completed")
    query=query.order_by(ChatMessage.position.desc())
    if limit is not None:query=query.limit(limit)
    rows=list(db.scalars(query))
    requests = defaultdict(dict)
    for row in reversed(rows):
        requests[row.request_id][row.role] = row
    return [(v["user"], v["assistant"]) for v in requests.values()
            if "user" in v and "assistant" in v and not MEMORY_COMMAND.match(v["user"].content) and v["assistant"].position == v["user"].position + 1]


def reference_payload(references):
    # 提示词只带承接对话所需内容；UUID等完整出处留在后端及界面，不重复占据模型窗口。
    return [{key:entry[key] for key in ("kind","role","position","text") if key in entry} for entry in references]


def references_cost(references):
    return cost(json.dumps(reference_payload(references),ensure_ascii=False)) if references else 0


def summary_references(db, conversation_id, before_position, budget):
    summary = db.get(ConversationMemorySummary, conversation_id)
    if not summary or summary.through_position >= before_position:
        return []
    try:
        entries = json.loads(summary.summary_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    ids=[item.get("source_id") for item in entries[:16] if isinstance(item,dict) and isinstance(item.get("source_id"),str)]
    sources = {row.id: row for row in db.scalars(select(ChatMessage).where(
        ChatMessage.id.in_(ids), ChatMessage.conversation_id == conversation_id, ChatMessage.position <= summary.through_position,
        ChatMessage.status == "completed"))}
    result = []
    for item in entries[:16]:
        if not isinstance(item, dict):
            continue
        source = sources.get(item.get("source_id"))
        text = item.get("text")
        if source:
            question=db.scalar(select(ChatMessage).where(ChatMessage.conversation_id==conversation_id,
                ChatMessage.request_id==source.request_id,ChatMessage.role=="user"))
            if question and MEMORY_COMMAND.match(question.content):
                continue
        if not source or not isinstance(text, str) or not text.strip() or text not in safe_text(source.content) or SECRET.search(source.content):
            continue
        entry = {"kind": "conversation_summary", "conversation_id": conversation_id,
                 "source_id": source.id, "role": source.role, "position":source.position,
                 "created_at":source.created_at.isoformat(), "text": text}
        if references_cost(result+[entry]) <= budget:
            result.append(entry)
    return result


def build_context(db, conversation_id, before_position, *, budget=16000):
    from .settings import effective_settings
    from ...shared.models import ChatConversation
    conversation=db.scalar(select(ChatConversation).where(ChatConversation.id==conversation_id))
    enabled=not conversation or effective_settings(db,conversation.user_id,conversation_id)["history_enabled"]
    summary=db.get(ConversationMemorySummary,conversation_id) if enabled else None
    references=summary_references(db,conversation_id,before_position,budget) if enabled else []
    # 检查点覆盖过的前缀不再重复装入近期历史。关闭记忆时仍按预算选取近期问答。
    through=summary.through_position if summary and references and summary.through_position<before_position else -1
    pairs=completed_pairs(db,conversation_id,before_position,after_position=through,limit=None)
    remaining=max(0,budget-references_cost(references))
    selected=[]
    for pair in reversed(pairs):
        messages=[{"role":row.role,"content":safe_text(row.content)} for row in pair]
        used=sum(cost(m["content"]) for m in messages)
        if used>remaining:break
        selected[0:0]=messages;remaining-=used
    return MemoryContext(selected,references)

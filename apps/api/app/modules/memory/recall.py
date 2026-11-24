"""先做数据库权限过滤，再检索；返回原消息，不把索引副本当事实。"""
import hashlib
import logging
import re
from sqlalchemy import select, or_, and_, tuple_
from ...core.config import get_settings
from ...core.telemetry import traced, annotate
from ...core.model_budget import quota_user
from ...shared.models import ChatConversation, ChatMessage, ChatMemoryIndex, Lesson, ConversationMemoryPolicy
from .context import SECRET, MEMORY_COMMAND, cost
from .embeddings import embed

logger = logging.getLogger(__name__)


def scoped_messages(conversation, before_position):
    query = select(ChatMessage).join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id).where(
        ChatConversation.user_id == conversation.user_id, ChatMessage.status == "completed",
        ChatConversation.id.not_in(select(ConversationMemoryPolicy.conversation_id).where(ConversationMemoryPolicy.temporary.is_(True))),
        or_(ChatMessage.conversation_id != conversation.id, ChatMessage.position < before_position))
    commands=select(ChatMessage.conversation_id,ChatMessage.request_id).where(ChatMessage.role=="user",
        or_(*(ChatMessage.content.like(prefix+mark+"%") for prefix in ("记住","全局记住","忘记","修改记忆") for mark in (":","："))))
    query=query.where(tuple_(ChatMessage.conversation_id,ChatMessage.request_id).not_in(commands))
    # 主对话可跨课程；课程对话不吸收其他课程或全局聊天；课次对话仅限本课次。
    if conversation.lesson_id:
        query = query.where(ChatConversation.lesson_id == conversation.lesson_id)
    elif conversation.course_id:
        query = query.where(or_(ChatConversation.course_id == conversation.course_id,
            ChatConversation.lesson_id.in_(select(Lesson.id).where(Lesson.course_id == conversation.course_id))))
    return query


def terms_for(question):
    chunks = re.findall(r"[a-zA-Z0-9_]{2,}|[\u3400-\u9fff]{2,}", question[:1000])
    terms=[]
    for chunk in chunks:
        if re.fullmatch(r"[\u3400-\u9fff]+",chunk) and len(chunk)>4:
            terms += [chunk[i:i+2] for i in range(len(chunk)-1)]
        else:
            terms.append(chunk.lower())
    return list(dict.fromkeys(terms))[:32]


@traced("memory.recall")
def recall(db, conversation, question, before_position, *, budget=1600):
    from .settings import effective_settings
    if not effective_settings(db,conversation.user_id,conversation.id)["history_enabled"]:
        return []
    query=scoped_messages(conversation,before_position)
    terms=terms_for(question)
    conditions=[ChatMessage.content.ilike("%"+t.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%",escape="\\") for t in terms]
    rows=list(db.scalars(query.where(or_(*conditions)).order_by(ChatMessage.created_at.desc()).limit(80))) if conditions else []
    ranked={r.id:float(sum(t in r.content.lower() for t in terms))/max(1,len(terms)) for r in rows}
    by_id={r.id:r for r in rows}
    if db.get_bind().dialect.name == "postgresql" and get_settings().memory_semantic_enabled:
        try:
            vector=embed(question[:1000],timeout=3)
            if vector is not None:
                distance=ChatMemoryIndex.embedding.cosine_distance(vector)
                with db.begin_nested():
                    matches=db.execute(query.join(ChatMemoryIndex,ChatMemoryIndex.message_id==ChatMessage.id)
                        .where(ChatMemoryIndex.model==get_settings().embedding_model)
                        .add_columns(distance.label("distance"),ChatMemoryIndex.content_hash)
                        .order_by(distance).limit(12)).all()
                for row,dist,digest in matches:
                    if dist is not None and dist<0.35 and hashlib.sha256(row.content.encode()).hexdigest()==digest:
                        by_id[row.id]=row
                        ranked[row.id]=ranked.get(row.id,0)+1-dist
        except Exception:
            logger.info("Memory semantic recall unavailable")
    result=[]
    for identity in sorted(ranked,key=lambda k:ranked[k],reverse=True):
        row=by_id[identity]
        if SECRET.search(row.content):
            continue
        # 读取每个来源会话设置，临时对话、关闭历史的来源不参与召回。
        if not effective_settings(db,conversation.user_id,row.conversation_id)["history_enabled"]:
            continue
        text=row.content[:400]
        entry={"kind":"chat_history","conversation_id":row.conversation_id,"source_id":row.id,
            "role":row.role,"text":text,"created_at":row.created_at.isoformat()}
        if cost(str(entry))>budget:
            continue
        result.append(entry);budget-=cost(str(entry))
        if len(result)>=4:
            break
    annotate(result_count=len(result),candidate_limit=80,selected_count=len(result))
    return result


def index_conversation(db, conversation_id):
    if not get_settings().memory_semantic_enabled:
        return 0
    from .settings import effective_settings
    conversation=db.scalar(select(ChatConversation).where(ChatConversation.id==conversation_id))
    if not conversation or not effective_settings(db,conversation.user_id,conversation_id)["history_enabled"]:
        return 0
    rows=list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id==conversation_id,
        ChatMessage.status=="completed").order_by(ChatMessage.position.desc()).limit(12)))
    blocked={row.request_id for row in db.scalars(select(ChatMessage).where(ChatMessage.conversation_id==conversation_id,
        ChatMessage.role=="user")) if MEMORY_COMMAND.match(row.content)}
    count=0
    for row in rows:
        if row.request_id in blocked:
            continue
        if SECRET.search(row.content) or len(row.content.encode())>6000:
            continue
        digest=hashlib.sha256(row.content.encode()).hexdigest()
        saved=db.get(ChatMemoryIndex,row.id)
        if saved and saved.content_hash==digest and saved.model==get_settings().embedding_model:
            continue
        with quota_user(db,conversation.user_id):
            vector=embed(row.content)
        if vector is None:
            break
        # 重新校验删除、开关和原文，避免任务在禁用后补写索引。
        db.expire_all()
        current=db.scalar(select(ChatMessage).where(ChatMessage.id==row.id))
        if not current or hashlib.sha256(current.content.encode()).hexdigest()!=digest or not effective_settings(db,conversation.user_id,conversation_id)["history_enabled"]:
            db.rollback();return count
        db.merge(ChatMemoryIndex(message_id=current.id,embedding=vector,model=get_settings().embedding_model,content_hash=digest))
        db.commit();count+=1
    return count

from sqlalchemy import select
from ...shared.models import ChatMemoryUse, ChatMessage, ChatConversation, UserMemory
from .context import SECRET
from .service import visible_memories
from .settings import effective_settings


def save_usage(db,message,context,user_id):
    for entry in getattr(context,"references",[]):
        memory_id=entry.get("memory_id")
        source_id=entry.get("source_id")
        if memory_id:
            memory=db.scalar(visible_memories(db,user_id).where(UserMemory.id==memory_id))
            if memory and memory.version==entry.get("version"):
                db.add(ChatMemoryUse(message_id=message.id,memory_id=memory.id,memory_version=memory.version))
        elif source_id:
            source=db.scalar(select(ChatMessage).join(ChatConversation,ChatConversation.id==ChatMessage.conversation_id)
                .where(ChatMessage.id==source_id,ChatConversation.user_id==user_id))
            if source and not SECRET.search(source.content) and entry.get("text","") in source.content:
                db.add(ChatMemoryUse(message_id=message.id,source_message_id=source.id,excerpt=entry["text"]))


def read_usage(db,message_id,user_id,conversation_id,*,entries=None,policy=None):
    policy=policy if policy is not None else effective_settings(db,user_id,conversation_id)
    result=[]
    entries=entries if entries is not None else db.scalars(select(ChatMemoryUse).where(ChatMemoryUse.message_id==message_id))
    for entry in entries:
        if entry.memory_id and policy["long_term_enabled"]:
            memory=db.scalar(visible_memories(db,user_id).where(UserMemory.id==entry.memory_id))
            if memory:
                result.append({"kind":"memory","id":memory.id,"text":memory.content if memory.version==entry.memory_version else "这条记忆已更新",
                    "changed":memory.version!=entry.memory_version})
        elif entry.source_message_id and policy["history_enabled"]:
            source=db.scalar(select(ChatMessage).join(ChatConversation,ChatConversation.id==ChatMessage.conversation_id)
                .where(ChatMessage.id==entry.source_message_id,ChatConversation.user_id==user_id))
            if source and not SECRET.search(source.content) and entry.excerpt in source.content and effective_settings(db,user_id,source.conversation_id)["history_enabled"]:
                result.append({"kind":"history","id":source.id,"conversation_id":source.conversation_id,"text":entry.excerpt})
    return result

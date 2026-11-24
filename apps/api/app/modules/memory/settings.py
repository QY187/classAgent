from sqlalchemy import select, delete
from ...shared.models import UserMemorySettings, ConversationMemoryPolicy, ChatConversation, ChatMessage, ChatMemoryIndex, ConversationMemorySummary


def effective_settings(db, user_id, conversation_id=None):
    settings=db.get(UserMemorySettings,user_id)
    policy=db.get(ConversationMemoryPolicy,conversation_id) if conversation_id else None
    temporary=bool(policy and policy.temporary)
    return {"history_enabled": bool(settings.history_enabled if settings else True) and not temporary,
            "long_term_enabled": bool(settings.long_term_enabled if settings else True) and not temporary,
            "temporary": temporary}


def clear_derived(db, user_id, conversation_id=None):
    conversations=select(ChatConversation.id).where(ChatConversation.user_id==user_id)
    if conversation_id:
        conversations=conversations.where(ChatConversation.id==conversation_id)
    messages=select(ChatMessage.id).where(ChatMessage.conversation_id.in_(conversations))
    db.execute(delete(ChatMemoryIndex).where(ChatMemoryIndex.message_id.in_(messages)))
    db.execute(delete(ConversationMemorySummary).where(ConversationMemorySummary.conversation_id.in_(conversations)))

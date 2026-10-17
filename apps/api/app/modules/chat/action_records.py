"""写入与执行回执同一事务提交；每条问题每种动作最多执行一次。"""
import json
from fastapi import HTTPException
from sqlalchemy import select
from ...shared.models import AgentAction, ChatMessage
from .access import owned_conversation
from .generation import GenerationStopped


def perform_for_message(db, conversation_id, username, message_id, token, tool, arguments, handler, validate):
    db.rollback()
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    message = db.scalar(select(ChatMessage).where(ChatMessage.id == message_id,
        ChatMessage.conversation_id == conversation_id, ChatMessage.role == "user"))
    if conversation.generation_token != token or message is None or message.status != "pending":
        raise GenerationStopped()
    previous = db.scalar(select(AgentAction).where(AgentAction.message_id == message_id, AgentAction.tool == tool))
    if previous:
        if json.loads(previous.arguments_json) != arguments:
            raise HTTPException(409, "这条问题已经执行过该动作，请查看执行结果；修改目标请发送新问题")
        result = json.loads(previous.result_json)
        validate(db, conversation, message, result)
        db.commit()
        return result
    validate(db, conversation, message, None)
    try:
        # handler 复用业务服务但不能自行提交，让实体和回执保持原子性。
        result = handler(db)
        db.add(AgentAction(message_id=message_id, tool=tool,
            arguments_json=json.dumps(arguments, ensure_ascii=False), result_json=json.dumps(result, ensure_ascii=False)))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise

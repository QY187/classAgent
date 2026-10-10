"""只保存来源已校验的回答快照，用于停止时保留已生成内容。"""
import json
from sqlalchemy.orm import Session
from .access import owned_conversation
from .generation import GenerationStopped


def save_preview(db: Session, conversation_id: str, username: str, token: str, result: dict):
    db.rollback()
    conversation = owned_conversation(db, conversation_id, username, lock=True)
    if conversation.generation_token != token:
        raise GenerationStopped()
    conversation.generation_preview_json = json.dumps(result, ensure_ascii=False)
    db.commit()

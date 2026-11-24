from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from ...core.db import get_db
from ...core.deps import get_current_user
from ...core.ownership import user_id_for_username
from ...shared.models import UserMemory, UserMemorySettings, ConversationMemoryPolicy, ChatMessage, ChatConversation
from ..chat.access import owned_conversation
from ..chat.generation import is_generating
from .service import visible_memories, remember, validate_content
from .settings import effective_settings, clear_derived

router=APIRouter(tags=["memory"])


class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid")


class MemoryCreate(StrictModel):
    content:str=Field(min_length=2,max_length=300)
    course_id:str|None=None


class MemoryEdit(StrictModel):
    content:str=Field(min_length=2,max_length=300)
    version:int=Field(ge=1)


class SettingsEdit(StrictModel):
    history_enabled:StrictBool
    long_term_enabled:StrictBool


class PolicyEdit(StrictModel):
    temporary:StrictBool


def public(item):
    return {"id":item.id,"content":item.content,"course_id":item.course_id,"version":item.version,
            "source_message_id":item.source_message_id,"updated_at":item.updated_at}


@router.get("/memories")
def list_memories(username=Depends(get_current_user),db:Session=Depends(get_db)):
    user_id=user_id_for_username(db,username)
    return [public(r) for r in db.scalars(visible_memories(db,user_id).order_by(UserMemory.updated_at.desc()))]


@router.post("/memories",status_code=201)
def add_memory(body:MemoryCreate,username=Depends(get_current_user),db:Session=Depends(get_db)):
    user_id=user_id_for_username(db,username)
    if not effective_settings(db,user_id)["long_term_enabled"]:raise HTTPException(409,"请先启用长期记忆")
    item=remember(db,user_id,body.content,body.course_id);db.commit();db.refresh(item)
    return public(item)


@router.patch("/memories/{identity}")
def edit_memory(identity:str,body:MemoryEdit,username=Depends(get_current_user),db:Session=Depends(get_db)):
    user_id=user_id_for_username(db,username)
    item=db.scalar(visible_memories(db,user_id).where(UserMemory.id==identity))
    if item is None:raise HTTPException(404,"记忆不存在")
    changed=db.execute(update(UserMemory).where(UserMemory.id==identity,UserMemory.user_id==user_id,
        UserMemory.version==body.version).values(content=validate_content(body.content),version=body.version+1,source_message_id=None)).rowcount
    if not changed:raise HTTPException(409,"这条记忆已更新，请刷新后重试")
    db.commit();db.refresh(item);return public(item)


@router.delete("/memories/{identity}",status_code=204)
def delete_memory(identity:str,username=Depends(get_current_user),db:Session=Depends(get_db)):
    user_id=user_id_for_username(db,username)
    item=db.scalar(visible_memories(db,user_id).where(UserMemory.id==identity))
    if item is None:raise HTTPException(404,"记忆不存在")
    db.delete(item);db.commit()


@router.get("/memory-settings")
def get_memory_settings(username=Depends(get_current_user),db:Session=Depends(get_db)):
    return effective_settings(db,user_id_for_username(db,username))


@router.patch("/memory-settings")
def edit_settings(body:SettingsEdit,username=Depends(get_current_user),db:Session=Depends(get_db)):
    user_id=user_id_for_username(db,username)
    db.merge(UserMemorySettings(user_id=user_id,**body.model_dump()))
    if not body.history_enabled:clear_derived(db,user_id)
    db.commit();return effective_settings(db,user_id)


@router.get("/chat/conversations/{identity}/memory-policy")
def get_policy(identity:str,username=Depends(get_current_user),db:Session=Depends(get_db)):
    conversation=owned_conversation(db,identity,username)
    return effective_settings(db,conversation.user_id,identity)


@router.patch("/chat/conversations/{identity}/memory-policy")
def edit_policy(identity:str,body:PolicyEdit,username=Depends(get_current_user),db:Session=Depends(get_db)):
    conversation=owned_conversation(db,identity,username,lock=True)
    if is_generating(conversation):raise HTTPException(409,"请等待回答完成后切换记忆模式")
    db.merge(ConversationMemoryPolicy(conversation_id=identity,temporary=body.temporary))
    if body.temporary:clear_derived(db,conversation.user_id,identity)
    db.commit();return effective_settings(db,conversation.user_id,identity)


@router.get("/memory-sources/{identity}")
def get_source(identity:str,username=Depends(get_current_user),db:Session=Depends(get_db)):
    user_id=user_id_for_username(db,username)
    row=db.scalar(select(ChatMessage).join(ChatConversation,ChatConversation.id==ChatMessage.conversation_id)
        .where(ChatMessage.id==identity,ChatConversation.user_id==user_id))
    if row is None:raise HTTPException(404,"来源消息不存在")
    owned_conversation(db,row.conversation_id,username)
    from .context import safe_text
    return {"id":row.id,"conversation_id":row.conversation_id,"role":row.role,"content":safe_text(row.content),"created_at":row.created_at}

import re
from fastapi import HTTPException
from sqlalchemy import select, or_, update, func
from ...shared.models import UserMemory, ChatConversation, ChatMessage, Course, Lesson, ConversationMemoryPolicy
from .context import SECRET, cost
from .settings import effective_settings


def validate_content(content):
    value=content.strip()
    if not 2<=len(value)<=300:
        raise HTTPException(422,"记忆内容请输入2到300字")
    if SECRET.search(value):
        raise HTTPException(422,"密码、令牌等凭据信息不能保存为记忆")
    return value


def visible_memories(db,user_id):
    temporary=select(ConversationMemoryPolicy.conversation_id).where(ConversationMemoryPolicy.temporary.is_(True))
    sources=select(ChatMessage.id).join(ChatConversation,ChatConversation.id==ChatMessage.conversation_id).where(
        ChatConversation.user_id==user_id,ChatConversation.id.not_in(temporary))
    courses=select(Course.id).where(Course.owner_id==user_id)
    return select(UserMemory).where(UserMemory.user_id==user_id,
        or_(UserMemory.course_id.is_(None),UserMemory.course_id.in_(courses)),
        or_(UserMemory.source_message_id.is_(None),UserMemory.source_message_id.in_(sources)))


def remember(db,user_id,content,course_id=None,source_message_id=None):
    content=validate_content(content)
    if course_id and not db.scalar(select(Course.id).where(Course.id==course_id,Course.owner_id==user_id)):
        raise HTTPException(404,"课程不存在")
    existing=db.scalar(visible_memories(db,user_id).where(UserMemory.content==content,UserMemory.course_id==course_id))
    if existing:
        existing.source_message_id=source_message_id
        existing.version+=1
        return existing
    count=db.scalar(select(func.count()).select_from(UserMemory).where(UserMemory.user_id==user_id))
    if count>=100:
        raise HTTPException(409,"最多保存100条记忆，请先整理已有记忆")
    item=UserMemory(user_id=user_id,content=content,course_id=course_id,source_message_id=source_message_id)
    db.add(item);db.flush()
    return item


def long_term_references(db,conversation,question,budget=1000):
    if not effective_settings(db,conversation.user_id,conversation.id)["long_term_enabled"]:
        return []
    course_id=conversation.course_id
    if conversation.lesson_id:
        course_id=db.scalar(select(Lesson.course_id).where(Lesson.id==conversation.lesson_id))
    # 全局偏好始终适用；课程偏好仅在绑定该课程的会话中适用，主对话不混入所有课程偏好。
    rows=list(db.scalars(visible_memories(db,conversation.user_id).where(or_(UserMemory.course_id.is_(None),
        UserMemory.course_id==course_id) if course_id else UserMemory.course_id.is_(None)).order_by(UserMemory.updated_at.desc()).limit(30)))
    result=[]
    for row in rows:
        if SECRET.search(row.content):continue
        entry={"kind":"user_stated_memory","memory_id":row.id,"version":row.version,"text":row.content,
               "source_id":row.source_message_id,"course_id":row.course_id}
        used=cost(str(entry))
        if used<=budget:
            result.append(entry);budget-=used
    return result


def explicit_command(db,conversation,question,request_id,existing=None):
    match=re.fullmatch(r"(全局记住|记住|忘记|修改记忆)[：:]\s*(.+)",question,re.S)
    if not match:return None
    action,value=match.groups()
    policy=effective_settings(db,conversation.user_id,conversation.id)
    if not policy["long_term_enabled"]:
        answer="当前未启用长期记忆，请在记忆管理中开启；临时对话不会读写长期记忆。"
    else:
        course_id=conversation.course_id
        if conversation.lesson_id:
            course_id=db.scalar(select(Lesson.course_id).where(Lesson.id==conversation.lesson_id))
        if action=="全局记住":course_id=None
        # 与聊天保存同一事务。原请求幂等检查由调用方完成。
        answer=None
    position=db.scalar(select(func.max(ChatMessage.position)).where(ChatMessage.conversation_id==conversation.id)) or 0
    if existing and existing.position!=position:
        raise HTTPException(409,"此问题之后已有新消息，请重新发送")
    message=existing or ChatMessage(conversation_id=conversation.id,request_id=request_id,position=position+1,role="user",content=question)
    db.add(message);db.flush()
    if answer is None:
        try:
            if action in {"记住","全局记住"}:
                remember(db,conversation.user_id,value,course_id,message.id)
                answer="已记住："+value.strip()+("。仅用于当前课程。" if course_id else "。适用于你的其他对话。")
            else:
                old,new=value.split("=>",1) if action=="修改记忆" and "=>" in value else (value,None)
                matches=list(db.scalars(visible_memories(db,conversation.user_id).where(UserMemory.content==old.strip()).with_for_update()))
                if len(matches)!=1:
                    answer="没有找到唯一匹配的记忆。请在记忆管理中选择要修改或删除的条目。"
                elif action=="忘记":
                    db.delete(matches[0]);answer="已删除这条长期记忆。原聊天记录仍保留。"
                elif new is None:
                    answer="修改格式：修改记忆：原内容 => 新内容。也可以在记忆管理中编辑。"
                else:
                    matches[0].content=validate_content(new);matches[0].version+=1
                    matches[0].source_message_id=message.id;answer="已更新这条记忆，旧内容停止使用。"
        except HTTPException as exc:
            answer=str(exc.detail)
    message.status="completed";message.error_message=None
    db.add(ChatMessage(conversation_id=conversation.id,request_id=request_id,position=message.position+1,role="assistant",content=answer))
    if conversation.title=="新对话":conversation.title=question[:40]
    conversation.generation_token=None;conversation.generating_at=None;conversation.generation_preview_json=None
    db.commit()
    return True

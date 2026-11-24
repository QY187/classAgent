"""上下文服务的策略入口；本阶段使用会话记忆，后续长期记忆提交扩展用户策略。"""

def effective_settings(db,user_id,conversation_id=None):
    return {"history_enabled":True,"long_term_enabled":False,"temporary":False}

from sqlalchemy import inspect, text


def prepare_chat_cancellation(engine) -> None:
    inspector = inspect(engine)
    if inspector.has_table("chat_conversations"):
        columns = {item["name"] for item in inspector.get_columns("chat_conversations")}
        if "generation_preview_json" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE chat_conversations ADD COLUMN generation_preview_json TEXT"))
    if not inspector.has_table("chat_messages"):
        return
    status = next((item for item in inspector.get_check_constraints("chat_messages")
                   if item["name"] == "ck_chat_message_status"), None)
    if status and "cancelled" in status["sqltext"]:
        return
    with engine.begin() as connection:
        if status:
            connection.execute(text("ALTER TABLE chat_messages DROP CONSTRAINT ck_chat_message_status"))
        connection.execute(text("ALTER TABLE chat_messages ADD CONSTRAINT ck_chat_message_status CHECK (status IN ('pending', 'completed', 'failed', 'cancelled'))"))


def prepare_chat_scope(engine) -> None:
    """保留已有课次对话，增加互斥的课程对话归属。"""
    inspector = inspect(engine)
    if not inspector.has_table("chat_conversations"):
        return
    columns = {column["name"]: column for column in inspector.get_columns("chat_conversations")}
    constraints = {item["name"] for item in inspector.get_check_constraints("chat_conversations")}
    with engine.begin() as connection:
        if "course_id" not in columns:
            connection.execute(text("ALTER TABLE chat_conversations ADD COLUMN course_id VARCHAR(36) REFERENCES courses(id) ON DELETE CASCADE"))
        if not columns["lesson_id"]["nullable"]:
            connection.execute(text("ALTER TABLE chat_conversations ALTER COLUMN lesson_id DROP NOT NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_conversations_course_id ON chat_conversations (course_id)"))
        if "ck_chat_conversation_scope" not in constraints:
            connection.execute(text("ALTER TABLE chat_conversations ADD CONSTRAINT ck_chat_conversation_scope CHECK ((lesson_id IS NOT NULL AND course_id IS NULL) OR (lesson_id IS NULL AND course_id IS NOT NULL))"))

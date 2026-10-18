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
    """保留课程和课次对话，并允许两种归属均为空的主对话。"""
    inspector = inspect(engine)
    if inspector.has_table("chat_messages") and "agent_steps_json" not in {item["name"] for item in inspector.get_columns("chat_messages")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE chat_messages ADD COLUMN agent_steps_json TEXT NOT NULL DEFAULT '[]'"))
    if not inspector.has_table("chat_conversations"):
        return
    columns = {column["name"]: column for column in inspector.get_columns("chat_conversations")}
    constraints = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints("chat_conversations")}
    with engine.begin() as connection:
        if "course_id" not in columns:
            connection.execute(text("ALTER TABLE chat_conversations ADD COLUMN course_id VARCHAR(36) REFERENCES courses(id) ON DELETE CASCADE"))
        if not columns["lesson_id"]["nullable"]:
            connection.execute(text("ALTER TABLE chat_conversations ALTER COLUMN lesson_id DROP NOT NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_conversations_course_id ON chat_conversations (course_id)"))
        current = constraints.get("ck_chat_conversation_scope", "")
        if "lesson_id is null or course_id is null" not in current.lower().replace("(", "").replace(")", ""):
            if current:
                connection.execute(text("ALTER TABLE chat_conversations DROP CONSTRAINT ck_chat_conversation_scope"))
            connection.execute(text("ALTER TABLE chat_conversations ADD CONSTRAINT ck_chat_conversation_scope CHECK (lesson_id IS NULL OR course_id IS NULL)"))


def prepare_chat_pinning(engine) -> None:
    """为存量对话补充置顶状态；旧对话默认不置顶，可重复执行。"""
    inspector = inspect(engine)
    if inspector.has_table("chat_conversations") and "is_pinned" not in {
        item["name"] for item in inspector.get_columns("chat_conversations")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE chat_conversations ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT FALSE"))


def prepare_chat_archive(engine) -> None:
    inspector = inspect(engine)
    if inspector.has_table("chat_conversations") and "is_archived" not in {
        item["name"] for item in inspector.get_columns("chat_conversations")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE chat_conversations ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE"))

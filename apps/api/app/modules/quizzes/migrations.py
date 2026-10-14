from sqlalchemy import inspect, text


def prepare_quiz_scope(engine) -> None:
    """存量小测沿用原单课次字段，新小测可以保存多个指定课次。"""
    inspector = inspect(engine)
    if inspector.has_table("quizzes"):
        with engine.begin() as connection:
            if "agent_request_key" not in {column["name"] for column in inspector.get_columns("quizzes")}:
                connection.execute(text("ALTER TABLE quizzes ADD COLUMN agent_request_key VARCHAR(36)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_quizzes_agent_request_key ON quizzes (agent_request_key)"))
    if inspector.has_table("quizzes") and "lesson_ids_json" not in {column["name"] for column in inspector.get_columns("quizzes")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE quizzes ADD COLUMN lesson_ids_json TEXT"))

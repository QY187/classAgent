from sqlalchemy import inspect, text


def prepare_deleted_columns(engine):
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in ("courses", "lessons", "course_materials"):
            if inspector.has_table(table) and "deleted_at" not in {col["name"] for col in inspector.get_columns(table)}:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE"))

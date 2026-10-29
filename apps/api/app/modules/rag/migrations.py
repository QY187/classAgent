"""RAG 索引结构的幂等迁移。"""
from sqlalchemy import inspect, text


def prepare_document_chunks(engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("document_chunks"):
        return
    columns = {item["name"] for item in inspector.get_columns("document_chunks")}
    with engine.begin() as connection:
        if "parent_id" not in columns:
            connection.execute(text("ALTER TABLE document_chunks ADD COLUMN parent_id VARCHAR(36) REFERENCES document_chunks(id) ON DELETE CASCADE"))
        if "chunk_level" not in columns:
            connection.execute(text("ALTER TABLE document_chunks ADD COLUMN chunk_level VARCHAR(20) NOT NULL DEFAULT 'child'"))
        if "chunk_index" not in columns:
            connection.execute(text("ALTER TABLE document_chunks ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 0"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_document_chunks_parent_id ON document_chunks (parent_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_document_chunks_chunk_level ON document_chunks (chunk_level)"))

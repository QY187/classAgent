from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text

from .core.config import get_settings
from .core.db import Base, SessionLocal, engine
from .core.passwords import hash_password
from .modules.auth.controller import router as auth_router
from .modules.courses.controller import router as courses_router
from .modules.lessons.controller import router as lessons_router
from .modules.lessons.controller import audio_router
from .modules.search.controller import router as search_router
from .modules.summaries.controller import router as summaries_router
from .shared.models import User
from .modules.rag.controller import router as rag_router
from .modules.review_cards.controller import router as review_cards_router
from .modules.materials.controller import router as materials_router
from .modules.quizzes.controller import router as quizzes_router


app = FastAPI(title="ClassAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def prepare_database() -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    _prepare_course_owner_columns()
    _prepare_user_avatar_column()
    _prepare_course_material_columns()
    _prepare_lesson_sort_column()
    Base.metadata.create_all(bind=engine)
    _seed_root_user()
    _backfill_course_owner_ids()


def _prepare_lesson_sort_column() -> None:
    inspector = inspect(engine)
    if inspector.has_table("lessons") and "sort_order" not in {column["name"] for column in inspector.get_columns("lessons")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE lessons ADD COLUMN sort_order INTEGER"))


def _prepare_course_owner_columns() -> None:
    """在 ORM 检查现有表之前补齐存量课程的归属列。"""
    inspector = inspect(engine)
    if not inspector.has_table("courses"):
        return
    columns = {column["name"] for column in inspector.get_columns("courses")}
    with engine.begin() as connection:
        if "owner_username" not in columns:
            connection.execute(text("ALTER TABLE courses ADD COLUMN owner_username VARCHAR(100)"))
            connection.execute(text("UPDATE courses SET owner_username = :owner"), {"owner": get_settings().admin_username})
        if "owner_id" not in columns:
            connection.execute(text("ALTER TABLE courses ADD COLUMN owner_id VARCHAR(36)"))


def _prepare_user_avatar_column() -> None:
    inspector = inspect(engine)
    if inspector.has_table("users") and "avatar_content_type" not in {column["name"] for column in inspector.get_columns("users")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN avatar_content_type VARCHAR(32)"))


def _prepare_course_material_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("course_materials"):
        return
    columns = {column["name"] for column in inspector.get_columns("course_materials")}
    with engine.begin() as connection:
        if "source" not in columns:
            connection.execute(text("ALTER TABLE course_materials ADD COLUMN source VARCHAR(30) NOT NULL DEFAULT 'external'"))
        if "status" not in columns:
            connection.execute(text("ALTER TABLE course_materials ADD COLUMN status VARCHAR(30) NOT NULL DEFAULT 'stored'"))


def _backfill_course_owner_ids() -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE courses SET owner_username = :owner WHERE owner_username IS NULL AND owner_id IS NULL"), {"owner": get_settings().admin_username})
        connection.execute(text("UPDATE courses SET owner_id = users.id FROM users WHERE courses.owner_id IS NULL AND courses.owner_username = users.username"))
        missing = connection.scalar(text("SELECT COUNT(*) FROM courses WHERE owner_id IS NULL"))
        if missing:
            raise RuntimeError(f"有 {missing} 门课程无法关联到现有用户，请先核对归属数据")
        connection.execute(text("ALTER TABLE courses ALTER COLUMN owner_id SET NOT NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_courses_owner_id ON courses (owner_id)"))
    if not any("owner_id" in fk.get("constrained_columns", []) for fk in inspect(engine).get_foreign_keys("courses")):
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE courses ADD CONSTRAINT courses_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id)"))


def _seed_root_user() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            db.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
            db.commit()


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(courses_router)
app.include_router(lessons_router)
app.include_router(audio_router)
app.include_router(search_router)
app.include_router(summaries_router)
app.include_router(rag_router)
app.include_router(review_cards_router)
app.include_router(materials_router)
app.include_router(quizzes_router)

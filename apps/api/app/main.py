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
    Base.metadata.create_all(bind=engine)
    _backfill_course_owners()
    _seed_root_user()


def _backfill_course_owners() -> None:
    """无 Alembic 的轻量迁移：为存量 courses 表补 owner_username 列并划给管理员。"""
    inspector = inspect(engine)
    if not inspector.has_table("courses"):
        return
    columns = {column["name"] for column in inspector.get_columns("courses")}
    if "owner_username" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE courses ADD COLUMN owner_username VARCHAR(100)"))
        connection.execute(
            text("UPDATE courses SET owner_username = :owner"),
            {"owner": get_settings().admin_username},
        )


def _seed_root_user() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == settings.admin_username)) is None:
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

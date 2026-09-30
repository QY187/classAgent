from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.db import Base, engine
from .core.deps import get_current_user
from .modules.auth.controller import router as auth_router
from .modules.courses.controller import router as courses_router
from .modules.lessons.controller import router as lessons_router
from .modules.search.controller import router as search_router
from .modules.summaries.controller import router as summaries_router


app = FastAPI(title="ClassAgent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(courses_router)
app.include_router(lessons_router)
app.include_router(search_router)
app.include_router(summaries_router)

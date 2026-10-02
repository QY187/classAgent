from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from . import mapper


router = APIRouter(tags=["search"], dependencies=[Depends(get_current_user)])


@router.get("/search")
def search(
    q: str = Query("", min_length=1),
    course_id: str | None = None,
    kind: Literal["all", "courses", "lessons", "transcript", "summaries", "review_cards"] = "all",
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return mapper.search_all(db, q.strip(), username, course_id=course_id, kind=kind)

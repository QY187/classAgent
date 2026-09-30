from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from . import mapper


router = APIRouter(tags=["search"], dependencies=[Depends(get_current_user)])


@router.get("/search")
def search(q: str = Query("", min_length=1), db: Session = Depends(get_db)) -> dict:
    return mapper.search_all(db, q.strip())

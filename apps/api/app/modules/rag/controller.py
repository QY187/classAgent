from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from ...core.config import get_settings
from fastapi import HTTPException
from .service import index_status, owned_course


router = APIRouter(prefix="/courses/{course_id}", tags=["course-qa"])


@router.get("/index-status")
def get_index_status(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return index_status(db, course_id, username)


@router.post("/reindex", status_code=202)
def reindex_course(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    owned_course(db, course_id, username)
    if not get_settings().dashscope_api_key:
        raise HTTPException(status_code=503, detail="未配置 DASHSCOPE_API_KEY，无法建立课程问答索引")
    from ...infrastructure.tasks import reindex_course as task
    result = task.delay(course_id)
    return {"task_id": result.id, "status": "queued"}

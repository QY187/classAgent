from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from ...shared.schemas import CourseMaterialRead
from . import service


router = APIRouter(tags=["materials"])


@router.get("/courses/{course_id}/materials", response_model=list[CourseMaterialRead])
def list_materials(course_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_materials(db, course_id, username)


@router.post("/courses/{course_id}/materials", response_model=CourseMaterialRead, status_code=201)
def upload_material(course_id: str, file: UploadFile = File(...), lesson_id: str | None = Form(None),
                    username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.upload_material(db, course_id, lesson_id, file, username)

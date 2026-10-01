import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

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


@router.get("/courses/{course_id}/materials/{material_id}/file")
def material_file(course_id: str, material_id: str, download: bool = False,
                  username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    material, path, must_remove = service.get_material_file(db, course_id, material_id, username)
    return FileResponse(path, media_type=material.content_type, filename=material.filename,
                        content_disposition_type="attachment" if download else "inline",
                        background=BackgroundTask(os.unlink, path) if must_remove else None)


@router.get("/courses/{course_id}/materials/{material_id}/preview")
def material_preview(course_id: str, material_id: str,
                     username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    material, path, must_remove = service.get_material_file(db, course_id, material_id, username)
    try:
        text, truncated = service.preview_text(path, material.filename)
        return {"text": text, "truncated": truncated}
    finally:
        if must_remove:
            os.unlink(path)


@router.get("/courses/{course_id}/materials/{material_id}/preview.pdf")
def material_pdf_preview(course_id: str, material_id: str,
                         username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    material, path, must_remove = service.get_material_file(db, course_id, material_id, username)
    try:
        converted, directory = service.convert_office_to_pdf(path, material.filename)
    except Exception:
        if must_remove:
            os.unlink(path)
        raise
    return FileResponse(converted, media_type="application/pdf", filename=f"{os.path.splitext(material.filename)[0]}.pdf",
                        content_disposition_type="inline",
                        background=BackgroundTask(service.cleanup_converted_preview, directory, path if must_remove else None))

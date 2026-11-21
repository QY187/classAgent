from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response, JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from .schemas import CourseExport
from .service import build_course_archive

router = APIRouter(tags=["exports"])


class ExportResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            from pathlib import Path
            Path(self.path).unlink(missing_ok=True)


@router.post("/courses/{course_id}/export")
def export_course(course_id: str, payload: CourseExport, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    path, filename = build_course_archive(db, course_id, payload, username)
    return ExportResponse(path, media_type="application/zip", filename=filename,
                          headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/courses/{course_id}/export/preview")
def preview_course(course_id: str, payload: CourseExport, document: str | None = Query(default=None, max_length=300),
                   username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """枚举与读取同一导出范围，文档名只在归档条目中匹配，不访问用户路径。"""
    from zipfile import ZipFile
    path, _ = build_course_archive(db, course_id, payload, username, preview_document=document or "")
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if document is None:
                return JSONResponse({"documents": sorted(names, key=lambda name: (name != "课程目录.pdf", name))}, headers={"Cache-Control": "private, no-store"})
            if document not in names:
                raise HTTPException(404, "预览文档不存在或不在当前导出范围内，请刷新列表")
            return Response(archive.read(document), media_type="application/pdf", headers={
                "Content-Disposition": "inline", "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff"})
    finally:
        path.unlink(missing_ok=True)

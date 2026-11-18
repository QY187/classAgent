from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
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

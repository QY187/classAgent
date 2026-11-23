from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from . import service
from .schemas import EntryWrite, ImportEntries, SemesterWrite


router = APIRouter(prefix="/timetable", tags=["timetable"])


@router.get("/semesters")
def semesters(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_semesters(db, username)


@router.post("/semesters", status_code=201)
def create_semester(payload: SemesterWrite, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_semester(db, username, payload)


@router.put("/semesters/{semester_id}")
def update_semester(semester_id: str, payload: SemesterWrite, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_semester(db, username, payload, semester_id)


@router.post("/semesters/{semester_id}/activate")
def activate(semester_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.activate_semester(db, semester_id, username)


@router.delete("/semesters/{semester_id}", status_code=204)
def delete_semester(semester_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_semester(db, semester_id, username)


@router.get("/semesters/{semester_id}/entries")
def entries(semester_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_entries(db, semester_id, username)


@router.post("/semesters/{semester_id}/entries", status_code=201)
def create_entry(semester_id: str, payload: EntryWrite, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_entry(db, semester_id, username, payload)


@router.put("/semesters/{semester_id}/entries/{entry_id}")
def update_entry(semester_id: str, entry_id: str, payload: EntryWrite, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save_entry(db, semester_id, username, payload, entry_id)


@router.delete("/semesters/{semester_id}/entries/{entry_id}", status_code=204)
def delete_entry(semester_id: str, entry_id: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_entry(db, semester_id, entry_id, username)


@router.post("/semesters/{semester_id}/import/preview")
def preview_import(semester_id: str, file: UploadFile = File(...), username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    from .importing import MAX_FILE_BYTES
    service.owned_semester(db, semester_id, username)
    try:
        return service.preview_import(db, semester_id, username, (file.filename or "课表.pdf")[:200], file.file.read(MAX_FILE_BYTES + 1))
    finally:
        file.file.close()


@router.post("/semesters/{semester_id}/import")
def import_entries(semester_id: str, payload: ImportEntries, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.import_entries(db, semester_id, username, payload.entries)


@router.get("/week")
def week(semester_id: str | None = None, week: int | None = Query(default=None, ge=1, le=52),
         username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.week_view(db, username, semester_id, week)

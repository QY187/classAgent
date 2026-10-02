from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.db import get_db
from ...core.deps import get_current_user
from .queries import list_items
from .restore import restore_item
from .purge import purge_item
from .file_cleanup import clean_pending_files, pending_count

router = APIRouter(prefix="/recycle-bin", tags=["recycle-bin"])


@router.get("")
def list_recycled_items(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_items(db, username)


@router.post("/{kind}/{identity}/restore")
def restore_recycled_item(kind: str, identity: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return restore_item(db, kind, identity, username)


@router.delete("/{kind}/{identity}")
def purge_recycled_item(kind: str, identity: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return purge_item(db, kind, identity, username)


@router.get("/file-cleanup")
def file_cleanup_status(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"pending": pending_count(db, username)}


@router.post("/file-cleanup")
def retry_file_cleanup(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return clean_pending_files(db, username)

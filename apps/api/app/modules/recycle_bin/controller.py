from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.db import get_db
from ...core.deps import get_current_user
from .queries import list_items
from .restore import restore_item

router = APIRouter(prefix="/recycle-bin", tags=["recycle-bin"])


@router.get("")
def list_recycled_items(username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_items(db, username)


@router.post("/{kind}/{identity}/restore")
def restore_recycled_item(kind: str, identity: str, username: str = Depends(get_current_user), db: Session = Depends(get_db)):
    return restore_item(db, kind, identity, username)

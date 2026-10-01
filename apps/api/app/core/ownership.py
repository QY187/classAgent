from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..shared.models import User


def user_id_for_username(db: Session, username: str) -> str:
    user_id = db.scalar(select(User.id).where(User.username == username))
    if user_id is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user_id

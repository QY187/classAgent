from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .security import verify_token
from ..shared.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def _resolve(value: str | None, db: Session) -> str:
    if not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = verify_token(value)
    user = db.scalar(select(User).where(User.id == user_id)) if user_id else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user.username


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)) -> str:
    return _resolve(credentials.credentials if credentials is not None and credentials.scheme.lower() == "bearer" else None, db)


def get_current_user_flexible(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None, description="媒体元素无法携带请求头时的替代凭证"),
    db: Session = Depends(get_db),
) -> str:
    value = credentials.credentials if credentials is not None else token
    return _resolve(value, db)

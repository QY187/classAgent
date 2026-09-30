from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import verify_token

bearer_scheme = HTTPBearer(auto_error=False)


def _resolve(value: str | None) -> str:
    if not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = verify_token(value)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> str:
    return _resolve(credentials.credentials if credentials is not None and credentials.scheme.lower() == "bearer" else None)


def get_current_user_flexible(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None, description="媒体元素无法携带请求头时的替代凭证"),
) -> str:
    value = credentials.credentials if credentials is not None else token
    return _resolve(value)

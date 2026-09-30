from fastapi import HTTPException, status

from ...core.config import get_settings
from ...core.security import create_access_token


def authenticate(username: str, password: str) -> str:
    settings = get_settings()
    if username != settings.admin_username or password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return username


def issue_token(username: str) -> str:
    return create_access_token(username)

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.passwords import hash_password, verify_password
from ...core.security import create_access_token, create_refresh_token, verify_token
from ...shared.models import User


def authenticate(db: Session, username: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return user


def register_user(db: Session, username: str, password: str) -> User:
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被占用")
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def issue_access_token(username: str) -> str:
    return create_access_token(username)


def issue_refresh_token(username: str) -> str:
    return create_refresh_token(username)


def username_from_refresh(token: str) -> str:
    username = verify_token(token, expected_type="refresh")
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    return username

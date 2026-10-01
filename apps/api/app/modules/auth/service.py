from io import BytesIO

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...core.passwords import hash_password, verify_password
from ...infrastructure.storage import upload_file
from ...core.security import (
    create_access_token,
    create_refresh_token,
    revoke_all_for_user,
    revoke_refresh,
    verify_refresh_token,
)
from ...shared.models import Course, User

MAX_AVATAR_BYTES = 2 * 1024 * 1024


def avatar_object_key(user_id: str) -> str:
    return f"avatars/{user_id}"


def _avatar_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def save_avatar(db: Session, username: str, data: bytes) -> User:
    if not data or len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="头像文件不能为空，且不能超过 2 MB")
    content_type = _avatar_type(data)
    if content_type is None:
        raise HTTPException(status_code=400, detail="头像仅支持 PNG、JPG 或 WebP 图片")
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    upload_file(avatar_object_key(user.id), BytesIO(data), len(data), content_type)
    user.avatar_content_type = content_type
    db.commit()
    return user


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


def user_by_username(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    return user


def change_password(db: Session, username: str, current_password: str, new_password: str) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
    if current_password == new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同")
    revoke_all_for_user(user.id)
    user.password_hash = hash_password(new_password)
    db.commit()


def change_username(db: Session, username: str, current_password: str, new_username: str) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
    if new_username == username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新用户名与当前用户名相同")
    if db.scalar(select(User.id).where(User.username == new_username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被占用")
    revoke_all_for_user(user.id)
    db.execute(update(Course).where(Course.owner_id == user.id).values(owner_username=new_username))
    user.username = new_username
    db.commit()


def issue_access_token(user_id: str) -> str:
    return create_access_token(user_id)


def issue_refresh_token(user_id: str) -> str:
    return create_refresh_token(user_id)


def rotate_refresh(db: Session, old_refresh_token: str) -> tuple[str, str]:
    """校验旧 refresh（签名 + Redis 未吊销），吊销旧 jti 并签发新的一对 token。"""
    user_id, jti = verify_refresh_token(old_refresh_token)
    if user_id is None or db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    revoke_refresh(jti)
    return create_access_token(user_id), create_refresh_token(user_id)


def revoke_refresh_token(old_refresh_token: str | None) -> None:
    if not old_refresh_token:
        return
    _user_id, jti = verify_refresh_token(old_refresh_token)
    revoke_refresh(jti)


def revoke_user_sessions(db: Session, username: str) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        revoke_all_for_user(user.id)

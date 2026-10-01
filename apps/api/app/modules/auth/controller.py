from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ...core.db import get_db
from ...core.config import get_settings
from ...core.deps import get_current_user
from ...infrastructure.storage import materialize_file
from . import service
from .schemas import ChangePasswordRequest, ChangeUsernameRequest, LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserInfo, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserInfo:
    if not get_settings().allow_registration:
        raise HTTPException(status_code=403, detail="当前站点未开放注册")
    user = service.register_user(db, payload.username, payload.password)
    return UserInfo(username=user.username, has_avatar=bool(user.avatar_content_type))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = service.authenticate(db, payload.username, payload.password)
    return TokenResponse(
        access_token=service.issue_access_token(user.id),
        refresh_token=service.issue_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    access_token, refresh_token = service.rotate_refresh(db, payload.refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
def logout(payload: RefreshRequest) -> dict:
    service.revoke_refresh_token(payload.refresh_token)
    return {"status": "ok"}


@router.post("/logout-all")
def logout_all(username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service.revoke_user_sessions(db, username)
    return {"status": "ok"}


@router.get("/me", response_model=UserInfo)
def me(username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> UserInfo:
    user = service.user_by_username(db, username)
    return UserInfo(username=user.username, has_avatar=bool(user.avatar_content_type))


@router.get("/avatar")
def get_avatar(username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    user = service.user_by_username(db, username)
    if not user.avatar_content_type:
        raise HTTPException(status_code=404, detail="尚未上传头像")
    try:
        path, temporary = materialize_file(service.avatar_object_key(user.id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="头像文件不存在，请重新上传") from exc
    return FileResponse(path, media_type=user.avatar_content_type, headers={"Cache-Control": "no-store"}, background=BackgroundTask(path.unlink, missing_ok=True) if temporary else None)


@router.post("/avatar", response_model=UserInfo)
def upload_avatar(file: UploadFile = File(...), username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> UserInfo:
    data = file.file.read(service.MAX_AVATAR_BYTES + 1)
    user = service.save_avatar(db, username, data)
    return UserInfo(username=user.username, has_avatar=True)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service.change_password(db, username, payload.current_password, payload.new_password)
    return {"status": "ok"}


@router.post("/change-username")
def change_username(payload: ChangeUsernameRequest, username: str = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service.change_username(db, username, payload.current_password, payload.new_username)
    return {"status": "ok"}

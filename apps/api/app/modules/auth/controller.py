from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.config import get_settings
from ...core.deps import get_current_user
from . import service
from .schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserInfo, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserInfo:
    if not get_settings().allow_registration:
        raise HTTPException(status_code=403, detail="当前站点未开放注册")
    user = service.register_user(db, payload.username, payload.password)
    return UserInfo(username=user.username)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = service.authenticate(db, payload.username, payload.password)
    return TokenResponse(
        access_token=service.issue_access_token(user.username),
        refresh_token=service.issue_refresh_token(user.username),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest) -> TokenResponse:
    access_token, refresh_token = service.rotate_refresh(payload.refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
def logout(payload: RefreshRequest) -> dict:
    service.revoke_refresh_token(payload.refresh_token)
    return {"status": "ok"}


@router.post("/logout-all")
def logout_all(username: str = Depends(get_current_user)) -> dict:
    service.revoke_user_sessions(username)
    return {"status": "ok"}


@router.get("/me", response_model=UserInfo)
def me(username: str = Depends(get_current_user)) -> UserInfo:
    return UserInfo(username=username)

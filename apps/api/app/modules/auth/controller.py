from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.deps import get_current_user
from . import service
from .schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserInfo, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserInfo:
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
    username = service.username_from_refresh(payload.refresh_token)
    return TokenResponse(
        access_token=service.issue_access_token(username),
        refresh_token=service.issue_refresh_token(username),
    )


@router.get("/me", response_model=UserInfo)
def me(username: str = Depends(get_current_user)) -> UserInfo:
    return UserInfo(username=username)

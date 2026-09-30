from fastapi import APIRouter, Depends

from ...core.deps import get_current_user
from . import service
from .schemas import LoginRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    username = service.authenticate(payload.username, payload.password)
    return TokenResponse(access_token=service.issue_token(username))


@router.get("/me", response_model=UserInfo)
def me(username: str = Depends(get_current_user)) -> UserInfo:
    return UserInfo(username=username)

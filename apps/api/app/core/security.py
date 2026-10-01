import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .config import get_settings


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_token(user_id: str, token_type: str, lifetime_minutes: int, jti: str | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=lifetime_minutes)
    payload = {"sub": user_id, "typ": token_type, "exp": expire.isoformat(), "jti": jti or uuid4().hex}
    payload_json = json.dumps(payload).encode("utf-8")
    payload_text = _b64encode(payload_json)
    payload_bytes = payload_text.encode("ascii")
    signature = hmac.new(settings.secret_key.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return f"{payload_text}.{_b64encode(signature)}"


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    return create_token(user_id, "access", settings.access_token_expire_minutes)


def create_refresh_token(user_id: str) -> str:
    settings = get_settings()
    jti = uuid4().hex
    token = create_token(user_id, "refresh", settings.refresh_token_expire_minutes, jti=jti)
    _store_refresh(jti, user_id, settings.refresh_token_expire_minutes)
    return token


def verify_token(token: str, expected_type: str = "access") -> str | None:
    settings = get_settings()
    try:
        payload_text, signature_text = token.split(".")
    except ValueError:
        return None
    payload_bytes = payload_text.encode("ascii")
    expected = hmac.new(settings.secret_key.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    try:
        provided = _b64decode(signature_text)
    except (ValueError, base64.binascii.Error):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        payload = json.loads(_b64decode(payload_text))
        expire = datetime.fromisoformat(payload["exp"])
    except (ValueError, KeyError, base64.binascii.Error):
        return None
    if expire < datetime.now(timezone.utc):
        return None
    # 旧版 token 没有 typ 字段，按 access 处理，避免升级后全员强制掉线
    if payload.get("typ", "access") != expected_type:
        return None
    return payload.get("sub")


def verify_refresh_token(token: str) -> tuple[str | None, str | None]:
    """返回 (username, jti)；校验签名 + Redis 中是否仍存在（未吊销/未过期）。"""
    user_id = verify_token(token, expected_type="refresh")
    if user_id is None:
        return None, None
    try:
        jti = json.loads(_b64decode(token.split(".")[0])).get("jti")
    except (ValueError, KeyError, base64.binascii.Error):
        return None, None
    if not jti:
        return None, None
    from .redis_client import get_redis

    if not get_redis().exists(f"refresh:{jti}"):
        return None, None
    return user_id, jti


def revoke_refresh(jti: str | None) -> None:
    if not jti:
        return
    from .redis_client import get_redis

    client = get_redis()
    user_id = client.get(f"refresh:{jti}")
    client.delete(f"refresh:{jti}")
    if user_id:
        client.srem(f"refresh_user:{user_id}", jti)


def revoke_all_for_user(user_id: str) -> None:
    from .redis_client import get_redis

    client = get_redis()
    for jti in client.smembers(f"refresh_user:{user_id}"):
        client.delete(f"refresh:{jti}")
    client.delete(f"refresh_user:{user_id}")


def _store_refresh(jti: str, user_id: str, ttl: int) -> None:
    from .redis_client import get_redis

    client = get_redis()
    client.set(f"refresh:{jti}", user_id, ex=ttl)
    client.sadd(f"refresh_user:{user_id}", jti)

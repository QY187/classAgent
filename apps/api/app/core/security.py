import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from .config import get_settings


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_access_token(username: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload_json = json.dumps({"sub": username, "exp": expire.isoformat()}).encode("utf-8")
    payload_text = _b64encode(payload_json)
    payload_bytes = payload_text.encode("ascii")
    signature = hmac.new(settings.secret_key.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return f"{payload_text}.{_b64encode(signature)}"


def verify_access_token(token: str) -> str | None:
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
    return payload.get("sub")

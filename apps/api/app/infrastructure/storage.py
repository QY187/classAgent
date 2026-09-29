from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from minio import Minio

from ..core.config import get_settings


def get_client() -> Minio:
    settings = get_settings()
    endpoint = settings.s3_endpoint.removeprefix("http://").removeprefix("https://")
    return Minio(endpoint, access_key=settings.s3_access_key, secret_key=settings.s3_secret_key, secure=settings.s3_secure)


def ensure_bucket() -> None:
    client = get_client()
    bucket = get_settings().s3_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(object_key: str, stream: BinaryIO, size: int, content_type: str) -> None:
    settings = get_settings()
    if settings.storage_backend == "local":
        target = Path(settings.local_storage_path) / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            while chunk := stream.read(1024 * 1024):
                output.write(chunk)
        return

    ensure_bucket()
    get_client().put_object(settings.s3_bucket, object_key, stream, size, content_type=content_type)


def materialize_file(object_key: str) -> tuple[Path, bool]:
    """Return a local path for an uploaded object and whether it must be removed."""
    settings = get_settings()
    if settings.storage_backend == "local":
        path = Path(settings.local_storage_path) / object_key
        if not path.is_file():
            raise FileNotFoundError(f"找不到已保存的音频文件: {path}")
        return path, False

    response = get_client().get_object(settings.s3_bucket, object_key)
    temporary = NamedTemporaryFile(prefix="classagent-audio-", suffix=Path(object_key).suffix, delete=False)
    try:
        for chunk in response.stream(1024 * 1024):
            temporary.write(chunk)
    finally:
        response.close()
        response.release_conn()
        temporary.close()
    return Path(temporary.name), True

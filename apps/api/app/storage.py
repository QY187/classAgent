from io import BufferedIOBase

from minio import Minio

from .config import get_settings


def get_client() -> Minio:
    settings = get_settings()
    endpoint = settings.s3_endpoint.removeprefix("http://").removeprefix("https://")
    return Minio(endpoint, access_key=settings.s3_access_key, secret_key=settings.s3_secret_key, secure=settings.s3_secure)


def ensure_bucket() -> None:
    client = get_client()
    bucket = get_settings().s3_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(object_key: str, stream: BufferedIOBase, size: int, content_type: str) -> None:
    ensure_bucket()
    get_client().put_object(get_settings().s3_bucket, object_key, stream, size, content_type=content_type)


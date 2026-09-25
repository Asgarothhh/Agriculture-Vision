from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_s3_client() -> BaseClient:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(s3={"addressing_style": "path"}),
    )


def _local_root() -> Path:
    root = Path(get_settings().local_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_path(key: str) -> Path:
    path = _local_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ensure_bucket() -> None:
    settings = get_settings()
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        client.create_bucket(Bucket=settings.s3_bucket)


def _put_local(key: str, data: bytes) -> str:
    _local_path(key).write_bytes(data)
    logger.warning("S3 unavailable, stored %s on disk", key)
    return key


def upload_fileobj(key: str, fileobj: BinaryIO, content_type: str = "application/octet-stream") -> str:
    settings = get_settings()
    payload = fileobj.read()
    try:
        ensure_bucket()
        get_s3_client().put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
        )
        return key
    except Exception as exc:
        logger.warning("S3 upload failed (%s), using local storage", exc)
        return _put_local(key, payload)


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    settings = get_settings()
    try:
        ensure_bucket()
        get_s3_client().put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key
    except Exception as exc:
        logger.warning("S3 upload failed (%s), using local storage", exc)
        return _put_local(key, data)


def download_bytes(key: str) -> bytes:
    settings = get_settings()
    local = _local_root() / key
    try:
        response = get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
        return response["Body"].read()
    except Exception:
        if local.exists():
            return local.read_bytes()
        raise


def delete_object(key: str) -> None:
    settings = get_settings()
    try:
        get_s3_client().delete_object(Bucket=settings.s3_bucket, Key=key)
    except Exception:
        pass
    path = _local_root() / key
    if path.exists():
        path.unlink()


def presigned_url(key: str, expires: int = 3600) -> str:
    settings = get_settings()
    try:
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception:
        return f"/api/v1/storage/{key}"

"""MinIO 对象存储：原始文件 / 知识文档 / 直播切片 / 素材产出。

用途：中台统一对象层，结构化进 MySQL、非结构化（原文/图片/音视频）进 MinIO，
MySQL 里只存 object_key，实现“大对象外置”。
"""
from __future__ import annotations

import io

from minio import Minio

from .config import get_settings
from .logging import get_logger

log = get_logger("shopmind.storage")

_client: Minio | None = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
    return _client


def ensure_bucket(bucket: str | None = None) -> str:
    bucket = bucket or get_settings().minio_bucket
    client = get_minio()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        log.info("创建 bucket：%s", bucket)
    return bucket


def put_text(key: str, content: str, bucket: str | None = None) -> str:
    bucket = ensure_bucket(bucket)
    data = content.encode("utf-8")
    get_minio().put_object(bucket, key, io.BytesIO(data), length=len(data), content_type="text/plain")
    return key


def get_text(key: str, bucket: str | None = None) -> str:
    bucket = bucket or get_settings().minio_bucket
    resp = get_minio().get_object(bucket, key)
    try:
        return resp.read().decode("utf-8")
    finally:
        resp.close()
        resp.release_conn()


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream", bucket: str | None = None) -> str:
    bucket = ensure_bucket(bucket)
    get_minio().put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)
    return key


def object_exists(key: str, bucket: str | None = None) -> bool:
    bucket = bucket or get_settings().minio_bucket
    try:
        get_minio().stat_object(bucket, key)
        return True
    except Exception:  # noqa: BLE001
        return False

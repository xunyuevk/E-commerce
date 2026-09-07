"""Redis 客户端：语义缓存 / 临时状态。

语义缓存在 P2 中基于 embedding 相似度实现（见 p2 semantic_cache），这里只提供底层 KV/JSON 原语。
"""
from __future__ import annotations

import json

import redis

from .config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def cache_get_json(key: str):
    raw = get_redis().get(key)
    return json.loads(raw) if raw else None


def cache_set_json(key: str, value, ttl: int | None = None) -> None:
    get_redis().set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)


def cache_delete(key: str) -> None:
    get_redis().delete(key)

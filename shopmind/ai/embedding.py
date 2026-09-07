"""Embedding：百炼 text-embedding-v4 / 硅基 bge-m3（OpenAI 兼容）+ mock 回退。"""
from __future__ import annotations

from ..config import get_settings
from ..logging import get_logger
from .base import Embedder, mock_hash_embed, post_with_retry

log = get_logger("shopmind.ai.embedding")


class OpenAICompatEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        resp = post_with_retry(
            url,
            json={"model": self.model, "input": texts, "encoding_format": "float"},
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        data = resp.json()["data"]
        data.sort(key=lambda x: x["index"])
        vectors = [d["embedding"] for d in data]
        if vectors and len(vectors[0]) != self.dim:
            log.warning("embedding 返回维度 %d 与配置 EMBEDDING_DIM=%d 不一致，请对齐", len(vectors[0]), self.dim)
        return vectors


class MockEmbedder:
    def __init__(self, dim: int):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [mock_hash_embed(t, self.dim) for t in texts]


_cached: Embedder | None = None


def get_embedder() -> Embedder:
    global _cached
    if _cached is None:
        s = get_settings()
        if s.is_mock("embedding"):
            log.info("Embedding 使用 mock 回退（维度 %d）", s.embedding_dim)
            _cached = MockEmbedder(s.embedding_dim)
        else:
            _cached = OpenAICompatEmbedder(s.embedding_base_url, s.embedding_api_key, s.embedding_model, s.embedding_dim)
    return _cached

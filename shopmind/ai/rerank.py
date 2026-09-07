"""Rerank：硅基 bge-reranker-v2-m3（/rerank 端点）+ mock 回退。"""
from __future__ import annotations

from ..config import get_settings
from ..logging import get_logger
from .base import Reranker, mock_rerank, post_with_retry

log = get_logger("shopmind.ai.rerank")


class SiliconFlowReranker:
    """硅基流动 /rerank 端点（OpenAI 兼容风格）。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> tuple[list[int], list[float]]:
        payload = {"model": self.model, "query": query, "documents": documents}
        if top_n:
            payload["top_n"] = top_n
        resp = post_with_retry(
            f"{self.base_url}/rerank",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        results = resp.json()["results"]
        indices = [r["index"] for r in results]
        scores = [float(r["relevance_score"]) for r in results]
        return indices, scores


class DashScopeReranker:
    """阿里百炼(DashScope) 原生 rerank（如 qwen3.7-text-rerank）。

    与硅基不同：DashScope 不是 OpenAI 兼容，参数要包在 input/parameters 里，
    响应在 output.results。同一种能力、不同协议 → 抽象接口 + 多实现（面试可讲）。
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")  # 如 https://dashscope.aliyuncs.com
        self.api_key = api_key
        self.model = model

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> tuple[list[int], list[float]]:
        url = f"{self.base_url}/api/v1/services/rerank/text-rerank/text-rerank"
        payload = {
            "model": self.model,
            "input": {"query": query, "documents": documents},
            "parameters": {"return_documents": False},
        }
        if top_n:
            payload["parameters"]["top_n"] = top_n
        resp = post_with_retry(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=60,
        )
        results = resp.json()["output"]["results"]
        indices = [int(r["index"]) for r in results]
        scores = [float(r["relevance_score"]) for r in results]
        return indices, scores


class MockReranker:
    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> tuple[list[int], list[float]]:
        return mock_rerank(query, documents, top_n)


_cached: Reranker | None = None


def get_reranker() -> Reranker:
    global _cached
    if _cached is None:
        s = get_settings()
        provider = s.effective_provider("rerank")
        if s.is_mock("rerank"):
            _cached = MockReranker()
        elif provider == "dashscope":
            _cached = DashScopeReranker(s.rerank_base_url, s.rerank_api_key, s.rerank_model)
        else:
            _cached = SiliconFlowReranker(s.rerank_base_url, s.rerank_api_key, s.rerank_model)
    return _cached

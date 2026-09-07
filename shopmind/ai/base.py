"""Provider 接口定义 + mock 公共算法。

mock 的目的：没有 API Key 也能把“数据 → 知识 → AI 应用”整条流水线跑通、拿到可复现数字；
填了真实 Key（.env 里 AI_PROVIDER 切到 openai-compatible / 具体 provider）即切换真实模型。
"""
from __future__ import annotations

import hashlib
import time
from typing import Protocol

import httpx

from ..text import tokenize

# 云端偶发限流/网络抖动的可重试状态码
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def post_with_retry(url: str, *, attempts: int = 3, base_delay: float = 1.0, **kwargs) -> httpx.Response:
    """带指数退避的 POST：对传输层错误（含 SSL EOF）与 429/5xx 重试。

    说明：409/400/401/403 这类业务错误不重试（说明配置或权限有问题，重试无意义）。
    """
    last: BaseException | None = None
    for i in range(attempts):
        try:
            resp = httpx.post(url, **kwargs)
            if resp.status_code in _RETRYABLE_STATUS:
                last = resp
                time.sleep(base_delay * (2 ** i))
                continue
            resp.raise_for_status()
            return resp
        except httpx.TransportError as exc:  # 连接/SSL/超时等传输层错误
            last = exc
            time.sleep(base_delay * (2 ** i))
    if isinstance(last, httpx.Response):
        last.raise_for_status()
    raise last or RuntimeError(f"请求失败：{url}")


class ChatLLM(Protocol):
    def chat(self, messages: list[dict], **kwargs) -> str: ...


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> tuple[list[int], list[float]]: ...


class ASR(Protocol):
    def transcribe(self, audio_ref: str, **kwargs) -> str | list[dict]: ...


class ImageGen(Protocol):
    def generate(self, prompt: str, **kwargs) -> bytes: ...


def mock_hash_embed(text: str, dim: int) -> list[float]:
    """确定性 mock embedding：token 哈希 → 桶累加 → 归一化。

    共享 token 越多余弦相似度越高，离线也能演示“语义相近召回”。
    """
    vec = [0.0] * dim
    for tok in tokenize(text):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = (sum(v * v for v in vec)) ** 0.5 or 1.0
    return [round(v / norm, 8) for v in vec]


def mock_rerank(query: str, documents: list[str], top_n: int | None = None) -> tuple[list[int], list[float]]:
    """确定性 mock rerank：query 与 doc 的 token 重叠余弦。"""
    qt = set(tokenize(query))
    scores: list[float] = []
    for doc in documents:
        dt = set(tokenize(doc))
        if not qt or not dt:
            scores.append(0.0)
        else:
            scores.append(len(qt & dt) / ((len(qt) ** 0.5) * (len(dt) ** 0.5)))
    order = sorted(range(len(documents)), key=lambda i: -scores[i])
    if top_n is not None:
        order = order[:top_n]
    return order, [round(scores[i], 6) for i in order]

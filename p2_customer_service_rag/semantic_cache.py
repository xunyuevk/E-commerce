"""P2 语义缓存：按 query embedding 相似度命中缓存，降低重复问题的 LLM 成本/延迟。

选型（面试可讲）：
  - 为什么不是精确字符串匹配：换一种说法（“怎么退款”→“钱多久退”）同义不同字；
  - demo 用 O(N) 线性扫描（缓存小），生产换 FAISS/向量库做近似最近邻，思路一致。
"""
from __future__ import annotations

import time

from shopmind.ai import get_embedder
from shopmind.cache import cache_get_json, cache_set_json

from .config import get_config

_CACHE_KEY = "shopmind:rag:semantic_cache"


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def lookup(query: str) -> dict | None:
    cfg = get_config()
    if not cfg.cache_enabled:
        return None
    entries = cache_get_json(_CACHE_KEY) or []
    if not entries:
        return None
    qv = get_embedder().embed([query])[0]
    best, best_sim = None, -1.0
    for e in entries:
        sim = _cos(qv, e["embedding"])
        if sim > best_sim:
            best_sim, best = sim, e
    if best is not None and best_sim >= cfg.cache_threshold:
        return {"answer": best["answer"], "similarity": round(best_sim, 4), "matched_query": best["query"]}
    return None


def store(query: str, answer: str) -> None:
    cfg = get_config()
    if not cfg.cache_enabled:
        return
    entries = cache_get_json(_CACHE_KEY) or []
    qv = get_embedder().embed([query])[0]
    entries.append({"query": query, "embedding": qv, "answer": answer, "ts": time.time()})
    if len(entries) > 500:
        entries = entries[-500:]
    cache_set_json(_CACHE_KEY, entries, ttl=cfg.cache_ttl)

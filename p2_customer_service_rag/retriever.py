"""P2 检索：混合检索 → 重排。

链路：query → embedding → 混合检索(ES BM25 + kNN, RRF) → 重排(bge-reranker) → top_k。
"""
from __future__ import annotations

from shopmind import es as es_client
from shopmind.ai import get_embedder, get_reranker
from shopmind.config import get_settings

from .config import get_config


def retrieve(
    query: str,
    top_k: int | None = None,
    rerank_top: int | None = None,
    alpha: float | None = None,
    rrf_k: int | None = None,
) -> tuple[list[dict], list[float], float]:
    """返回 (reranked_hits, rerank_scores, top_score)。"""
    cfg = get_config()
    s = get_settings()
    top_k = top_k or cfg.top_k
    rerank_top = rerank_top or cfg.rerank_top

    qvec = get_embedder().embed([query])[0]
    hits = es_client.search_hybrid(
        s.kb_index,
        query,
        qvec,
        size=top_k,
        alpha=cfg.alpha if alpha is None else alpha,
        rrf_k=cfg.rrf_k if rrf_k is None else rrf_k,
    )
    if not hits:
        return [], [], 0.0

    docs = [h["_source"]["content"] for h in hits]
    order, scores = get_reranker().rerank(query, docs, top_n=min(rerank_top, len(docs)))
    reranked = [hits[i] for i in order]
    top_score = max(scores) if scores else 0.0
    return reranked, scores, top_score

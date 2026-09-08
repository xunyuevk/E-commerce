"""P2 端到端问答流水线：语义缓存 → 混合检索+重排 → 拒答判断 → 生成 → 写回缓存。"""
from __future__ import annotations

import time

from .config import get_config
from .generator import generate
from .retriever import retrieve
from .semantic_cache import lookup, store

REFUSAL_MESSAGE = "抱歉，这个问题我暂时无法准确回答，建议您转人工客服处理。"


def answer(query: str, use_cache: bool = True) -> dict:
    cfg = get_config()
    t0 = time.time()

    # 1. 语义缓存
    if use_cache:
        hit = lookup(query)
        if hit:
            return {
                "answer": hit["answer"],
                "answerable": True,
                "confidence": hit["similarity"],
                "sources": [],
                "from_cache": True,
                "matched_query": hit["matched_query"],
                "latency_ms": _elapsed_ms(t0),
            }

    # 2. 检索 + 重排
    hits, scores, top_score = retrieve(query)

    # 3. 拒答判断（answerability）
    if not hits or top_score < cfg.refusal_threshold:
        return {
            "answer": REFUSAL_MESSAGE,
            "answerable": False,
            "confidence": round(top_score, 4),
            "sources": [],
            "from_cache": False,
            "matched_query": None,
            "latency_ms": _elapsed_ms(t0),
        }

    contexts_text = [h["_source"]["content"] for h in hits][: cfg.max_context_chunks]
    answer_text = generate(query, contexts_text)

    # 4. 写回语义缓存
    if use_cache:
        store(query, answer_text)

    sources = [
        {
            "title": h["_source"]["title"],
            "chunk_id": h["_source"]["chunk_id"],
            "source_type": h["_source"]["source_type"],
            "score": round(s, 4),
            "content": h["_source"]["content"][:200],
        }
        for h, s in zip(hits, scores)
    ]

    return {
        "answer": answer_text,
        "answerable": True,
        "confidence": round(top_score, 4),
        "sources": sources,
        "from_cache": False,
        "matched_query": None,
        "latency_ms": _elapsed_ms(t0),
    }


def analyze(query: str) -> dict:
    """只做 检索 + 重排 + 拒答判断，不做生成（用于快速评测检索/拒答质量，不调 LLM）。"""
    cfg = get_config()
    hits, scores, top_score = retrieve(query)
    answerable = bool(hits) and top_score >= cfg.refusal_threshold
    sources = [
        {
            "title": h["_source"]["title"],
            "chunk_id": h["_source"]["chunk_id"],
            "source_type": h["_source"]["source_type"],
            "score": round(s, 4),
        }
        for h, s in zip(hits, scores)
    ]
    return {"answerable": answerable, "confidence": round(top_score, 4), "sources": sources}


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)

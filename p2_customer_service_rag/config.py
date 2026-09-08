"""P2 关键配置：所有可调参数集中于此（面试重点：阈值调参）。

这些值是“评测驱动”出来的：先跑 eval 拿到基线，再调阈值，再复测。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass
class RAGConfig:
    # 切片
    chunk_size: int = field(default_factory=lambda: _i("CHUNK_SIZE", 500))
    chunk_overlap: int = field(default_factory=lambda: _i("CHUNK_OVERLAP", 50))

    # 检索
    top_k: int = field(default_factory=lambda: _i("TOP_K", 10))          # 混合检索召回数
    rerank_top: int = field(default_factory=lambda: _i("RERANK_TOP", 5))  # 重排后保留数
    alpha: float = field(default_factory=lambda: _f("HYBRID_ALPHA", 0.5))  # RRF 向量权重
    rrf_k: int = field(default_factory=lambda: _i("RRF_K", 60))

    # 拒答（answerability）—— 由 refusal 评测集校准
    # 说明：0.05 是 mock（token 重叠余弦）刻度下的默认值；切真实 rerank 后分数刻度不同，
    # 实测域内最低 0.85、域外最高 0.107，取 0.2 留足安全边际（见 p2 eval 扫参）。
    refusal_threshold: float = field(default_factory=lambda: _f("REFUSAL_THRESHOLD", 0.2))

    # 语义缓存
    cache_enabled: bool = field(default_factory=lambda: os.getenv("CACHE_ENABLED", "1") == "1")
    cache_threshold: float = field(default_factory=lambda: _f("CACHE_THRESHOLD", 0.92))  # 相似度阈值
    cache_ttl: int = field(default_factory=lambda: _i("CACHE_TTL", 3600))

    # 上下文给 LLM 的最大切片数
    max_context_chunks: int = field(default_factory=lambda: _i("MAX_CONTEXT_CHUNKS", 4))


def get_config() -> RAGConfig:
    return RAGConfig()

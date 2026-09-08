"""P3 商品关联：用 embedding 余弦相似度把直播切片关联到商品。

设计（面试可讲）：
  - 用「段文本」与「商品 name+description」分别 embedding，算余弦相似度取 top1~2，
    能捕捉同义/变体表述（如“耳机”↔“真无线蓝牙耳机 X”），比字符串关键词召回更全；
  - 阈值 0.2 过滤弱相关，避免「硬配」；mock embedding 是 token 哈希桶累加，
    共享 token 越多相似度越高，离线也能跑通链路。
"""
from __future__ import annotations

import math
import re

from shopmind import db
from shopmind.ai import get_embedder

SIM_THRESHOLD = 0.2
TOP_N = 2

_ROLE_RE = re.compile(r"^(?:主播|助播|观众|粉丝|用户)\s*[：:]\s*", flags=re.M)


def _cos(a: list[float], b: list[float]) -> float:
    """两个等长向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _clean(text: str) -> str:
    """剥掉角色前缀，得到用于 embedding 的纯净段文本。"""
    return _ROLE_RE.sub("", text).strip()


def link_products(segments: list[dict]) -> list[dict]:
    """给每段关联商品 id，写入各段的 ``product_ids``（list[int]），返回原列表。"""
    if not segments:
        return segments

    products = db.fetchall("SELECT id, name, description FROM product")
    if not products:
        for seg in segments:
            seg["product_ids"] = []
        return segments

    seg_texts = [_clean(seg["transcript"]) for seg in segments]
    prod_texts = [f"{p['name']} {p['description'] or ''}".strip() for p in products]

    emb = get_embedder()
    seg_vecs = emb.embed(seg_texts)
    prod_vecs = emb.embed(prod_texts)

    for seg, vec in zip(segments, seg_vecs):
        scored = sorted(
            ((j, _cos(vec, prod_vecs[j])) for j in range(len(products))),
            key=lambda x: -x[1],
        )
        seg["product_ids"] = [
            int(products[j]["id"]) for j, sim in scored[:TOP_N] if sim > SIM_THRESHOLD
        ]
    return segments

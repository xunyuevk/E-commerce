"""Elasticsearch 8：知识库索引 + 混合检索（BM25 + 向量 + RRF 融合）。

关键设计（面试重点）：
  - BM25 走 content_tokens 字段（jieba 预分词 + whitespace analyzer，免 ik 插件）；
  - 向量走 dense_vector（dims 与 EMBEDDING_DIM 对齐，cosine）；
  - 融合用 RRF（Reciprocal Rank Fusion）：对两路排序取倒数加和，无需归一化分数、
    对量纲不敏感，是工业界常用做法（Weaviate 等内置）。
"""
from __future__ import annotations

import time

from elasticsearch import Elasticsearch

from .config import get_settings
from .logging import get_logger
from .text import join_tokens

log = get_logger("shopmind.es")

_es: Elasticsearch | None = None


def get_es() -> Elasticsearch:
    global _es
    if _es is None:
        s = get_settings()
        _es = Elasticsearch(s.es_url, request_timeout=30, max_retries=2, retry_on_timeout=True)
    return _es


def wait_for_es(timeout: float = 180, interval: float = 3) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if get_es().ping():
                log.info("Elasticsearch 就绪")
                return
        except Exception as e:  # noqa: BLE001
            log.debug("等待 ES：%s", e)
        time.sleep(interval)
    raise TimeoutError(f"Elasticsearch 在 {timeout}s 内未就绪")


def ensure_index(index: str, dim: int) -> None:
    """创建知识库索引（幂等）。向量维度必须与 embedding 模型输出一致。"""
    es = get_es()
    if es.indices.exists(index=index):
        return
    body = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    # 预分词字段用 whitespace，避免再被 standard 二次切分
                    "shopmind_tokens": {"type": "custom", "tokenizer": "whitespace", "filter": ["lowercase"]},
                }
            },
        },
        "mappings": {
            "properties": {
                "doc_id": {"type": "long"},
                "chunk_id": {"type": "long"},
                "seq": {"type": "integer"},
                "title": {"type": "text", "analyzer": "standard"},
                "content": {"type": "text", "analyzer": "standard"},
                "content_tokens": {"type": "text", "analyzer": "shopmind_tokens"},
                "source_type": {"type": "keyword"},
                "category": {"type": "keyword"},
                "content_vector": {
                    "type": "dense_vector",
                    "dims": dim,
                    "index": True,
                    "similarity": "cosine",
                },
                "created_at": {"type": "date"},
            }
        },
    }
    es.indices.create(index=index, body=body)
    log.info("创建索引 %s（向量维度 %d）", index, dim)


def delete_index(index: str) -> None:
    es = get_es()
    if es.indices.exists(index=index):
        es.indices.delete(index=index)
        log.info("删除索引 %s", index)


def bulk_index_docs(index: str, docs: list[dict]) -> int:
    """批量写入文档。docs 需含 _id（chunk_id）。"""
    es = get_es()
    from elasticsearch.helpers import bulk

    actions = [
        {
            "_index": index,
            "_id": str(d.pop("_id")),
            "_source": d,
        }
        for d in docs
    ]
    ok, errors = bulk(es, actions, refresh=True)
    if errors:
        log.warning("部分文档写入失败：%s", errors[:3])
    log.info("写入 %s 共 %d 条", index, ok)
    return ok


def search_hybrid(
    index: str,
    query: str,
    vector: list[float],
    size: int = 10,
    alpha: float = 0.5,
    rrf_k: int = 60,
    filters: dict | None = None,
) -> list[dict]:
    """混合检索：BM25 + kNN，RRF 融合后返回 size 条。

    alpha：RRF 中向量路权重占比（0~1）；rrf_k：排序平滑常数。
    返回命中列表，每项含 _id/_score/highlight/_source。
    """
    es = get_es()

    filter_clauses = []
    if filters:
        for k, v in filters.items():
            if isinstance(v, (list, tuple)):
                filter_clauses.append({"terms": {k: v}})
            else:
                filter_clauses.append({"term": {k: v}})

    # 第 1 路：BM25（纯 query，对预分词字段 content_tokens 做 match）
    bm25_body: dict = {
        "size": size * 4,
        "query": {
            "bool": {
                "must": {"match": {"content_tokens": {"query": join_tokens(query)}}},
            }
        },
        "highlight": {
            "fields": {"content": {"fragment_size": 120, "number_of_fragments": 2}},
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
        },
    }
    if filter_clauses:
        bm25_body["query"]["bool"]["filter"] = filter_clauses
    bm25_resp = es.search(index=index, body=bm25_body)

    # 第 2 路：向量 kNN（纯 knn）
    knn_body: dict = {
        "size": size * 4,
        "knn": {
            "field": "content_vector",
            "query_vector": vector,
            "k": size * 4,
            "num_candidates": size * 8,
        },
    }
    knn_resp = es.search(index=index, body=knn_body)

    bm25_hits = bm25_resp["hits"]["hits"]
    knn_hits = knn_resp["hits"]["hits"]

    bm25_ranks = {h["_id"]: i + 1 for i, h in enumerate(bm25_hits)}
    knn_ranks = {h["_id"]: i + 1 for i, h in enumerate(knn_hits)}

    # RRF 融合（只依赖两路排名，不依赖分数绝对值）
    fused: dict[str, float] = {}
    for doc_id in set(bm25_ranks) | set(knn_ranks):
        score = 0.0
        if doc_id in bm25_ranks:
            score += (1 - alpha) / (rrf_k + bm25_ranks[doc_id])
        if doc_id in knn_ranks:
            score += alpha / (rrf_k + knn_ranks[doc_id])
        fused[doc_id] = score

    ranked_ids = sorted(fused, key=fused.get, reverse=True)[:size]

    # 以 BM25 结果为主（带 highlight），补上仅出现在 kNN 路的结果
    by_id = {h["_id"]: h for h in bm25_hits}
    for h in knn_hits:
        if h["_id"] not in by_id:
            by_id[h["_id"]] = h

    results = []
    for doc_id in ranked_ids:
        h = by_id.get(doc_id)
        if h is None:
            continue
        results.append(
            {
                "_id": h["_id"],
                "_score": round(fused[doc_id], 6),
                "highlight": h.get("highlight", {}),
                "_source": h["_source"],
            }
        )
    return results

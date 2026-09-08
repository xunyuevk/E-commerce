"""P2 知识入库（data → knowledge）：knowledge_doc + faq → 切片 → 向量 → ES。

幂等：重复执行会重建索引（清空 chunk/embedding_record、重置状态），适合反复做 chunk 实验。
"""
from __future__ import annotations

import json
from datetime import datetime

from shopmind import db
from shopmind import es as es_client
from shopmind.ai import get_embedder
from shopmind.config import get_settings
from shopmind.lineage import add_lineage, get_or_create_asset, record_audit, update_asset_row_count
from shopmind.logging import get_logger
from shopmind.storage import get_text, put_text
from shopmind.text import join_tokens

from .chunking import chunk_by_paragraphs
from .config import get_config

log = get_logger("p2.ingest")


def _ensure_faq_docs() -> int:
    """把 FAQ 表内容物化为知识文档（统一走 knowledge_doc → chunk 流程）。"""
    faqs = db.fetchall("SELECT * FROM faq WHERE enabled=1")
    count = 0
    for f in faqs:
        title = f["question"]
        existing = db.fetchone("SELECT id FROM knowledge_doc WHERE source_type='faq' AND title=:t", {"t": title})
        if existing:
            continue
        content = f"Q: {f['question']}\nA: {f['answer']}"
        key = f"knowledge/faq/{f['id']}.md"
        put_text(key, content)
        db.insert_get_id(
            "INSERT INTO knowledge_doc (title, source_type, object_key, doc_meta, status) "
            "VALUES (:t, 'faq', :ok, :meta, 'staged')",
            {"t": title, "ok": key,
             "meta": json.dumps({"category": f.get("category"), "faq_id": f["id"], "tags": f.get("tags")}, ensure_ascii=False)},
        )
        count += 1
    log.info("FAQ 物化为知识文档：新增 %d 条", count)
    return count


def _reset_index() -> None:
    s = get_settings()
    es_client.delete_index(s.kb_index)
    es_client.ensure_index(s.kb_index, s.embedding_dim)
    db.execute("DELETE FROM chunk")
    db.execute("DELETE FROM embedding_record")
    db.execute("UPDATE knowledge_doc SET status='staged', chunk_count=0")


def ingest_knowledge() -> dict:
    """执行完整知识入库，返回统计。"""
    s = get_settings()
    cfg = get_config()
    embedder = get_embedder()

    es_client.wait_for_es()
    db.wait_for_mysql()
    _reset_index()
    _ensure_faq_docs()

    docs = db.fetchall("SELECT * FROM knowledge_doc ORDER BY id")
    es_docs: list[dict] = []
    total_chunks = 0

    for doc in docs:
        content = get_text(doc["object_key"])
        chunks = chunk_by_paragraphs(content, cfg.chunk_size, cfg.chunk_overlap)
        for seq, chunk_text in enumerate(chunks):
            chunk_id = db.insert_get_id(
                "INSERT INTO chunk (doc_id, seq, content, token_count) VALUES (:d, :s, :c, :tc)",
                {"d": doc["id"], "s": seq, "c": chunk_text, "tc": len(chunk_text)},
            )
            vector = embedder.embed([chunk_text])[0]
            meta = json.loads(doc["doc_meta"]) if doc["doc_meta"] else {}
            es_docs.append(
                {
                    "_id": str(chunk_id),
                    "doc_id": doc["id"],
                    "chunk_id": chunk_id,
                    "seq": seq,
                    "title": doc["title"],
                    "content": chunk_text,
                    "content_tokens": join_tokens(chunk_text),
                    "source_type": doc["source_type"],
                    "category": meta.get("category"),
                    "content_vector": vector,
                    "created_at": datetime.now().isoformat(),
                }
            )
            db.execute(
                "INSERT INTO embedding_record (chunk_id, model, dim, es_doc_id) VALUES (:c, :m, :dim, :e)",
                {"c": chunk_id, "m": s.embedding_model, "dim": s.embedding_dim, "e": str(chunk_id)},
            )
            total_chunks += 1
        db.execute(
            "UPDATE knowledge_doc SET status='indexed', chunk_count=:c WHERE id=:id",
            {"c": len(chunks), "id": doc["id"]},
        )

    if es_docs:
        es_client.bulk_index_docs(s.kb_index, es_docs)

    # 资产 + 血缘（回血：业务表 → 知识索引）
    kb_asset = get_or_create_asset(
        s.kb_index, "index", f"es:{s.kb_index}", owner="p2", sensitivity="L2",
        description="客服知识库混合索引（BM25 + 向量）",
    )
    update_asset_row_count(s.kb_index, total_chunks)
    add_lineage("faq", s.kb_index, "feeds", "FAQ 切片入库")
    add_lineage("knowledge_doc", s.kb_index, "feeds", "政策/手册切片入库")
    record_audit("p2", "ingest_knowledge", kb_asset, {"chunks": total_chunks})

    result = {"documents": len(docs), "chunks": total_chunks, "index": s.kb_index}
    log.info("P2 知识入库完成：%s", json.dumps(result, ensure_ascii=False))
    return result

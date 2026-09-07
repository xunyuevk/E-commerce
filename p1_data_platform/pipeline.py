"""P1 流水线编排：采集 → 清洗 → 脱敏 → 资产化（发布 + 血缘 + 审计）。

这是“供血”主流程：原始数据进来，经清洗/脱敏后发布到业务表，
并把“表/文件”登记为资产、连出血缘，供 P2~P5 消费。
"""
from __future__ import annotations

import json
import re

from shopmind import db
from shopmind.lineage import (
    add_lineage,
    get_or_create_asset,
    mark_ingest,
    record_audit,
    register_source,
    update_asset_row_count,
)
from shopmind.logging import get_logger
from shopmind.storage import ensure_bucket, put_text

from . import clean, desensitize, seed_data

log = get_logger("p1")


def _register_rules() -> None:
    """把清洗/脱敏规则登记到平台（规则可配置、可审计）。"""
    cleaning_rules = [
        ("drop_null", "drop_null", {"required": ["name", "phone"]}),
        ("dedup", "dedup", {"by": "business_key"}),
        ("normalize_amount", "normalize", {"field": "total_amount"}),
        ("range_check", "range", {"price": {"min": 0}, "quantity": {"min": 1}}),
    ]
    for name, rtype, params in cleaning_rules:
        db.execute(
            "INSERT IGNORE INTO cleaning_rule (name, rule_type, params_json) VALUES (:n, :t, :p)",
            {"n": name, "t": rtype, "p": json.dumps(params, ensure_ascii=False)},
        )

    desens_rules = [
        ("mask_name", "name", "mask", None),
        ("mask_phone", "phone", "phone", None),
        ("mask_email", "email", "email", None),
        ("mask_idcard", "idcard", "idcard", None),
    ]
    for name, field, rtype, params in desens_rules:
        db.execute(
            "INSERT IGNORE INTO desensitization_rule (name, field, rule_type, params_json) VALUES (:n, :f, :t, :p)",
            {"n": name, "f": field, "t": rtype, "p": params},
        )
    log.info("清洗/脱敏规则已登记")


def _ingest_raw() -> dict[str, int]:
    """采集：原始数据写入 MinIO（模拟文件落地），并登记数据源。返回 source_id 映射。"""
    bucket = ensure_bucket()
    sources = {}
    datasets = {
        "raw_customers": seed_data.RAW_CUSTOMERS,
        "raw_products": seed_data.RAW_PRODUCTS,
        "raw_orders": seed_data.RAW_ORDERS,
        "raw_conversations": seed_data.RAW_CONVERSATIONS,
        "raw_tickets": seed_data.RAW_TICKETS,
        "raw_faq": seed_data.RAW_FAQ,
        "raw_knowledge_docs": seed_data.KNOWLEDGE_DOCS,
    }
    for name, rows in datasets.items():
        key = f"raw/{name}.json"
        put_text(key, json.dumps(rows, ensure_ascii=False, indent=2))
        sid = register_source(name, "minio", f"minio:{bucket}/{key}")
        sources[name] = sid
        log.info("采集原始数据 %s → %s（%d 条）", name, key, len(rows))
    return sources


def _slug(title: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", title.strip())
    return s.strip("_") or "doc"


def _clear_business_tables() -> None:
    """清空 P1 自己产出的业务表，保证 run_pipeline 幂等（可一键重建、误跑不重复）。"""
    # 只清 P1 播种的表；knowledge_doc 里 P2/P3 回血的 live_transcript/faq 文档不清
    db.execute("DELETE FROM order_item")
    db.execute("DELETE FROM orders")
    db.execute("DELETE FROM message")
    db.execute("DELETE FROM conversation")
    db.execute("DELETE FROM ticket")
    db.execute("DELETE FROM faq")
    db.execute("DELETE FROM customer")
    db.execute("DELETE FROM product")
    db.execute("DELETE FROM knowledge_doc WHERE source_type IN ('policy', 'manual')")


def _publish(clean_data: dict) -> dict:
    """发布：写入业务表 + 知识文档进 MinIO，返回资产行数。"""
    _clear_business_tables()
    rows_count: dict[str, int] = {}

    # 商品（无 PII）
    pid_map = {}
    for p in clean_data["products"]:
        pid = db.insert_get_id(
            "INSERT INTO product (sku, name, category, brand, price, stock, description, specs_json) "
            "VALUES (:sku, :name, :category, :brand, :price, :stock, :description, :specs)",
            {
                "sku": p["sku"], "name": p["name"], "category": p.get("category"),
                "brand": p.get("brand"), "price": p["price"], "stock": p["stock"],
                "description": p.get("description"),
                "specs": json.dumps(p.get("specs"), ensure_ascii=False),
            },
        )
        pid_map[p["sku"]] = pid
    rows_count["product"] = len(clean_data["products"])

    # 客户（脱敏后）
    cid_map = {}
    for c in clean_data["customers"]:
        d = desensitize.desensitize_customer(c)
        cid = db.insert_get_id(
            "INSERT INTO customer (customer_no, name_masked, phone_masked, email_masked, city, level) "
            "VALUES (:no, :nm, :pm, :em, :city, :lv)",
            {"no": d["customer_no"], "nm": d["name_masked"], "pm": d["phone_masked"],
             "em": d["email_masked"], "city": d["city"], "lv": d["level"]},
        )
        cid_map[c["cid"]] = cid
    rows_count["customer"] = len(clean_data["customers"])

    # 订单 + 明细
    item_count = 0
    for o in clean_data["orders"]:
        oid = db.insert_get_id(
            "INSERT INTO orders (order_no, customer_id, status, total_amount, channel) "
            "VALUES (:no, :cid, :st, :amt, :ch)",
            {"no": o["order_no"], "cid": cid_map[o["cid"]], "st": o["status"],
             "amt": o["total_amount"], "ch": o.get("channel", "app")},
        )
        for it in o["items"]:
            db.execute(
                "INSERT INTO order_item (order_id, product_id, quantity, price) VALUES (:o, :p, :q, :pr)",
                {"o": oid, "p": pid_map[it["sku"]], "q": it["quantity"], "pr": it["price"]},
            )
            item_count += 1
    rows_count["orders"] = len(clean_data["orders"])
    rows_count["order_item"] = item_count

    # 会话 + 消息
    msg_count = 0
    for conv in clean_data["conversations"]:
        cid = db.insert_get_id(
            "INSERT INTO conversation (conversation_no, customer_id, channel, intent, status, satisfaction) "
            "VALUES (:no, :cid, :ch, :intent, 'resolved', :sat)",
            {"no": conv["conversation_no"], "cid": cid_map[conv["cid"]],
             "ch": conv.get("channel", "online"), "intent": conv.get("intent"),
             "sat": conv.get("satisfaction")},
        )
        for m in conv["messages"]:
            db.execute(
                "INSERT INTO message (conversation_id, role, content) VALUES (:c, :r, :content)",
                {"c": cid, "r": m["role"], "content": m["content"]},
            )
            msg_count += 1
    rows_count["conversation"] = len(clean_data["conversations"])
    rows_count["message"] = msg_count

    # 工单
    for t in clean_data["tickets"]:
        db.execute(
            "INSERT INTO ticket (ticket_no, type, priority, status, assignee) VALUES (:no, :t, :p, :s, :a)",
            {"no": t["ticket_no"], "t": t["type"], "p": t["priority"], "s": t["status"], "a": t.get("assignee")},
        )
    rows_count["ticket"] = len(clean_data["tickets"])

    # FAQ（sku → product_id）
    for f in clean_data["faq"]:
        db.execute(
            "INSERT INTO faq (question, answer, category, tags, product_id) "
            "VALUES (:q, :a, :c, :t, :pid)",
            {"q": f["question"], "a": f["answer"], "c": f.get("category"), "t": f.get("tags"),
             "pid": pid_map.get(f["sku"]) if f.get("sku") else None},
        )
    rows_count["faq"] = len(clean_data["faq"])

    # 知识文档：正文进 MinIO，元数据进 MySQL（status=staged，等 P2 切片入库）
    for doc in seed_data.KNOWLEDGE_DOCS:
        key = f"knowledge/{_slug(doc['title'])}.md"
        put_text(key, doc["content"])
        db.execute(
            "INSERT INTO knowledge_doc (title, source_type, object_key, doc_meta, status) "
            "VALUES (:t, :st, :ok, :meta, 'staged')",
            {"t": doc["title"], "st": doc["source_type"], "ok": key,
             "meta": json.dumps({"category": doc.get("category")}, ensure_ascii=False)},
        )
    rows_count["knowledge_doc"] = len(seed_data.KNOWLEDGE_DOCS)

    return rows_count


def _register_assets_and_lineage(sources: dict[str, int], rows_count: dict[str, int]) -> None:
    """登记资产目录 + 血缘 + 审计，把“数据闭环”落到可查询结构。"""
    table_assets = {
        "customer": ("table", "mysql:shopmind.customer", "p1", "L3", "脱敏后客户主数据"),
        "product": ("table", "mysql:shopmind.product", "p1", "L1", "商品主数据"),
        "orders": ("table", "mysql:shopmind.orders", "p1", "L3", "订单"),
        "order_item": ("table", "mysql:shopmind.order_item", "p1", "L3", "订单明细"),
        "conversation": ("table", "mysql:shopmind.conversation", "p1", "L3", "客服会话"),
        "message": ("table", "mysql:shopmind.message", "p1", "L3", "会话消息"),
        "ticket": ("table", "mysql:shopmind.ticket", "p1", "L3", "工单"),
        "faq": ("table", "mysql:shopmind.faq", "p1", "L2", "FAQ 知识"),
        "knowledge_doc": ("table", "mysql:shopmind.knowledge_doc", "p1", "L2", "知识文档元数据"),
    }
    for name, (atype, loc, owner, sens, desc) in table_assets.items():
        aid = get_or_create_asset(name, atype, loc, owner=owner, sensitivity=sens, description=desc)
        if name in rows_count:
            update_asset_row_count(name, rows_count[name])
        record_audit("p1", "register_asset", aid, {"rows": rows_count.get(name, 0)})

    # 血缘
    lineage = [
        ("raw_customers", "customer", "feeds", "采集→清洗→脱敏"),
        ("raw_products", "product", "feeds", "采集→清洗"),
        ("raw_orders", "orders", "feeds", "采集→清洗"),
        ("orders", "order_item", "derives_from", "订单拆分明细"),
        ("raw_conversations", "conversation", "feeds", "采集→清洗"),
        ("conversation", "message", "derives_from", "会话拆消息"),
        ("raw_tickets", "ticket", "feeds", "采集"),
        ("raw_faq", "faq", "feeds", "采集→清洗"),
        ("raw_knowledge_docs", "knowledge_doc", "feeds", "采集→正文入对象存储"),
    ]
    for src, dst, rel, desc in lineage:
        if src.startswith("raw_"):
            add_lineage(
                src, dst, relation=rel, description=desc,
                src_type="object", src_location=f"minio:shopmind/raw/{src}.json",
            )
        else:
            add_lineage(src, dst, relation=rel, description=desc)

    for name, sid in sources.items():
        mark_ingest(sid, name, "success", rows_count.get(name.replace("raw_", ""), 0))


def run_pipeline() -> dict:
    """执行完整 P1 流水线，返回汇总结果。"""
    db.wait_for_mysql()
    ensure_bucket()

    _register_rules()
    sources = _ingest_raw()

    # 清洗
    customers, s1 = clean.clean_customers(seed_data.RAW_CUSTOMERS)
    products, s2 = clean.clean_products(seed_data.RAW_PRODUCTS)
    orders, s3 = clean.clean_orders(seed_data.RAW_ORDERS)
    conversations, s4 = clean.clean_conversations(seed_data.RAW_CONVERSATIONS)
    tickets, s5 = clean.clean_tickets(seed_data.RAW_TICKETS)
    faq, s6 = clean.clean_faq(seed_data.RAW_FAQ)

    clean_data = {
        "customers": customers, "products": products, "orders": orders,
        "conversations": conversations, "tickets": tickets, "faq": faq,
    }
    stats = {"customers": s1, "products": s2, "orders": s3,
             "conversations": s4, "tickets": s5, "faq": s6}

    rows_count = _publish(clean_data)
    _register_assets_and_lineage(sources, rows_count)

    summary = {
        "cleaning_stats": stats,
        "published_rows": rows_count,
        "sources": len(sources),
        "assets": 9,
        "lineage_edges": 9,
    }
    log.info("P1 流水线完成：%s", json.dumps(summary, ensure_ascii=False, default=str))
    return summary

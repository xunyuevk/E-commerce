"""数据血缘 & 资产目录 & 审计。

主线核心：P1 登记资产 + 血缘，P2~P5 每次“取数/回血”都追加一条血缘边，
从而把“数据 → 知识 → AI 应用 → 新数据回血”的闭环落到可查询的数据结构上。
"""
from __future__ import annotations

import json
from datetime import datetime

from .db import execute, fetchone
from .logging import get_logger

log = get_logger("shopmind.lineage")


def register_source(name: str, source_type: str, location: str, config: dict | None = None) -> int:
    execute(
        "INSERT IGNORE INTO data_source (name, source_type, location, config_json) "
        "VALUES (:n, :t, :l, :c)",
        {"n": name, "t": source_type, "l": location, "c": json.dumps(config, ensure_ascii=False) if config else None},
    )
    row = fetchone("SELECT id FROM data_source WHERE name=:n", {"n": name})
    return int(row["id"])


def get_or_create_asset(
    name: str,
    asset_type: str,
    location: str,
    owner: str | None = None,
    sensitivity: str = "L3",
    description: str | None = None,
) -> int:
    execute(
        "INSERT IGNORE INTO data_asset (name, asset_type, location, owner, sensitivity, description) "
        "VALUES (:n, :t, :l, :o, :s, :d)",
        {"n": name, "t": asset_type, "l": location, "o": owner, "s": sensitivity, "d": description},
    )
    row = fetchone("SELECT id FROM data_asset WHERE name=:n", {"n": name})
    return int(row["id"])


def update_asset_row_count(name: str, count: int) -> None:
    execute("UPDATE data_asset SET row_count=:c, updated_at=NOW() WHERE name=:n", {"c": count, "n": name})


def add_lineage(
    src_name: str,
    dst_name: str,
    relation: str = "feeds",
    description: str | None = None,
    src_type: str = "table",
    src_location: str | None = None,
    dst_type: str = "table",
    dst_location: str | None = None,
) -> None:
    src = get_or_create_asset(src_name, src_type, src_location or f"mysql:shopmind.{src_name}")
    dst = get_or_create_asset(dst_name, dst_type, dst_location or f"mysql:shopmind.{dst_name}")
    # 幂等：同一条 (src, dst, relation) 边只登记一次，重复执行流水线不累积重复血缘。
    exists = fetchone(
        "SELECT id FROM lineage_edge WHERE src_asset_id=:s AND dst_asset_id=:d AND relation=:r LIMIT 1",
        {"s": src, "d": dst, "r": relation},
    )
    if exists:
        return
    execute(
        "INSERT INTO lineage_edge (src_asset_id, dst_asset_id, relation, description) "
        "VALUES (:s, :d, :r, :desc)",
        {"s": src, "d": dst, "r": relation, "desc": description},
    )
    log.info("血缘：%s -[%s]-> %s", src_name, relation, dst_name)


def record_audit(actor: str, action: str, asset_id: int | None = None, detail: dict | None = None) -> None:
    execute(
        "INSERT INTO audit_log (actor, action, asset_id, detail_json) VALUES (:a, :act, :aid, :d)",
        {"a": actor, "act": action, "aid": asset_id, "d": json.dumps(detail, ensure_ascii=False) if detail else None},
    )


def mark_ingest(source_id: int, target_asset: str, status: str, rows: int, error: str | None = None) -> int:
    execute(
        "INSERT INTO ingest_job (source_id, target_asset, status, rows_ingested, error, started_at, finished_at) "
        "VALUES (:s, :t, :st, :r, :e, NOW(), NOW())",
        {"s": source_id, "t": target_asset, "st": status, "r": rows, "e": error},
    )
    row = fetchone("SELECT LAST_INSERT_ID() AS id")
    return int(row["id"])


def current_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

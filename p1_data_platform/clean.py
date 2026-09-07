"""P1 清洗：去空 / 去重 / 规范化 / 范围校验。

规则统一登记在 cleaning_rule 表（平台化），这里是对应的执行逻辑。
"""
from __future__ import annotations

import re


def _trim_strings(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        out[k] = v.strip() if isinstance(v, str) else v
    return out


def _clean_records(rows: list[dict], key: str, required: list[str], validators: dict[str, callable]) -> tuple[list[dict], dict]:
    stats = {"input": len(rows), "dropped_null": 0, "dropped_dup": 0, "dropped_invalid": 0}
    cleaned: list[dict] = []
    seen: set = set()
    for r in rows:
        r = _trim_strings(r)
        # 1. 去空：必填字段为空则丢弃
        if any(r.get(f) in (None, "") for f in required):
            stats["dropped_null"] += 1
            continue
        # 2. 去重：按业务键去重
        k = r.get(key)
        if k in seen:
            stats["dropped_dup"] += 1
            continue
        seen.add(k)
        # 3. 校验：任一校验器返回 False 则丢弃
        if any(not fn(r.get(f)) for f, fn in validators.items()):
            stats["dropped_invalid"] += 1
            continue
        cleaned.append(r)
    stats["output"] = len(cleaned)
    return cleaned, stats


# 各字段校验器
def valid_phone(v: str | None) -> bool:
    return bool(v) and re.fullmatch(r"1[3-9]\d{9}", v) is not None


def valid_email(v: str | None) -> bool:
    return bool(v) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) is not None


def valid_price(v) -> bool:
    return isinstance(v, (int, float)) and v >= 0


def valid_quantity(v) -> bool:
    return isinstance(v, int) and v > 0


def clean_customers(rows: list[dict]) -> tuple[list[dict], dict]:
    return _clean_records(
        rows,
        key="cid",
        required=["cid", "name", "phone"],
        validators={"phone": valid_phone, "email": valid_email},
    )


def clean_products(rows: list[dict]) -> tuple[list[dict], dict]:
    return _clean_records(
        rows,
        key="sku",
        required=["sku", "name"],
        validators={"price": valid_price, "stock": lambda v: isinstance(v, int) and v >= 0},
    )


def clean_orders(rows: list[dict]) -> tuple[list[dict], dict]:
    stats = {"input": len(rows), "dropped_null": 0, "dropped_dup": 0, "dropped_invalid": 0}
    cleaned, seen = [], set()
    for r in rows:
        r = _trim_strings(r)
        if not r.get("order_no") or r.get("cid") is None or not r.get("items"):
            stats["dropped_null"] += 1
            continue
        if r["order_no"] in seen:
            stats["dropped_dup"] += 1
            continue
        seen.add(r["order_no"])
        if any(it.get("quantity", 0) <= 0 or it.get("price", 0) < 0 for it in r["items"]):
            stats["dropped_invalid"] += 1
            continue
        # 规范化：金额由明细重算，保证一致性
        r["total_amount"] = round(sum(it["price"] * it["quantity"] for it in r["items"]), 2)
        cleaned.append(r)
    stats["output"] = len(cleaned)
    return cleaned, stats


def clean_conversations(rows: list[dict]) -> tuple[list[dict], dict]:
    return _clean_records(
        rows,
        key="conversation_no",
        required=["conversation_no", "cid"],
        validators={"cid": lambda v: isinstance(v, int) and v > 0},
    )


def clean_faq(rows: list[dict]) -> tuple[list[dict], dict]:
    return _clean_records(rows, key="question", required=["question", "answer"], validators={})


def clean_tickets(rows: list[dict]) -> tuple[list[dict], dict]:
    return _clean_records(rows, key="ticket_no", required=["ticket_no", "type"], validators={})

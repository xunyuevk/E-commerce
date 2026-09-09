"""P5 数据集构建：从真实客服会话抽取 SFT 微调语料。

规则：取「高满意度」（satisfaction >= min_satisfaction）会话中 customer ↔ agent 的对话，
抽出最后一轮问答对作为一条样本（user=customer 输入，assistant=agent 回复），
并套上统一客服人设 system 提示词，写成 OpenAI Chat 格式 JSONL。

产出：
  - 本地 data/sft_train.jsonl（finetune.py 读取）
  - MinIO finetune/sft_train.jsonl（回血中台）
  - 登记资产 sft_dataset + 血缘 conversation -> sft_dataset + 审计
"""
from __future__ import annotations

import json
from pathlib import Path

from shopmind import db
from shopmind.lineage import (
    add_lineage,
    get_or_create_asset,
    record_audit,
    update_asset_row_count,
)
from shopmind.logging import get_logger
from shopmind.storage import put_text

log = get_logger("p5.build_dataset")

# 统一客服人设：口语化、亲切、守规
SYSTEM_PROMPT = (
    "你是 ShopMind 电商平台的客服小助手「小音」。"
    "回复要亲切、口语化，像真人在聊天，多站在用户角度共情、安抚情绪；"
    "同时必须守规：不夸大、不承诺做不到的事，涉及退货/保修/退款等政策要准确，"
    "不确定就如实说明并引导转人工。"
)

MINIO_KEY = "finetune/sft_train.jsonl"
ASSET_LOCATION = f"minio:shopmind/{MINIO_KEY}"
DATA_DIR = Path(__file__).resolve().parent / "data"


def _extract_pair(messages: list[dict]) -> tuple[str, str] | None:
    """从按时间排序的消息里抽取最后一轮 (user, assistant) 问答对。

    - 最后一条是 agent：assistant=最后一条 agent，user=其上一条 customer；
    - 最后一条是 customer：user=最后一条 customer，assistant=其上一条 agent；
    - 抽不出完整问答对（如只有单侧消息）返回 None。
    """
    if not messages:
        return None
    last = messages[-1]
    if last["role"] == "agent":
        assistant = last["content"]
        for m in reversed(messages[:-1]):
            if m["role"] == "customer":
                return m["content"], assistant
    else:  # customer 结尾
        user = last["content"]
        for m in reversed(messages[:-1]):
            if m["role"] == "agent":
                return user, m["content"]
    return None


def build_sft_dataset(min_satisfaction: int = 4) -> dict:
    """从 conversation/message 表抽取 SFT 样本并落盘 + 回血 MinIO。

    返回统计：{conversations, samples, avg_user_len, avg_assistant_len}。
    """
    convs = db.fetchall(
        "SELECT id, conversation_no, satisfaction FROM conversation "
        "WHERE satisfaction >= :s ORDER BY id",
        {"s": min_satisfaction},
    )

    samples: list[dict] = []
    for conv in convs:
        msgs = db.fetchall(
            "SELECT role, content FROM message "
            "WHERE conversation_id = :c AND role IN ('customer', 'agent') "
            "ORDER BY id",
            {"c": conv["id"]},
        )
        pair = _extract_pair(msgs)
        if pair is None:
            continue
        user, assistant = pair
        samples.append(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]
            }
        )

    # 本地 JSONL（finetune.py 的直接输入）
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(s, ensure_ascii=False) for s in samples]
    text = "\n".join(lines) + ("\n" if lines else "")
    out = DATA_DIR / "sft_train.jsonl"
    out.write_text(text, encoding="utf-8")
    log.info("SFT 语料已写本地：%s（%d 条）", out, len(samples))

    # 回血 MinIO（不可用时不影响本地 JSONL 与统计）
    try:
        put_text(MINIO_KEY, text)
        log.info("SFT 语料已写 MinIO：%s", MINIO_KEY)
    except Exception as e:  # noqa: BLE001
        log.warning("MinIO 写入失败（本地 JSONL 不受影响）：%s", e)

    avg_user = (
        round(sum(len(s["messages"][1]["content"]) for s in samples) / len(samples), 1)
        if samples
        else 0.0
    )
    avg_assistant = (
        round(sum(len(s["messages"][2]["content"]) for s in samples) / len(samples), 1)
        if samples
        else 0.0
    )

    stats = {
        "conversations": len(convs),
        "samples": len(samples),
        "avg_user_len": avg_user,
        "avg_assistant_len": avg_assistant,
    }

    asset_id = get_or_create_asset(
        "sft_dataset",
        "file",
        ASSET_LOCATION,
        owner="p5",
        sensitivity="L2",
        description="真实客服会话抽取的拟人化 SFT 语料",
    )
    update_asset_row_count("sft_dataset", len(samples))
    add_lineage("conversation", "sft_dataset", "feeds", "真实会话→微调语料")
    record_audit("p5", "build_sft_dataset", asset_id, {"min_satisfaction": min_satisfaction, **stats})

    log.info("SFT 数据集构建完成：%s", json.dumps(stats, ensure_ascii=False))
    return stats

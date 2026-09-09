"""P5 before/after 双端点评测：base 模型 vs 微调模型。

真实对比需要配置两个真实端点（LLM_FINETUNED_BASE_URL / API_KEY / MODEL）；
mock 模式下两者都是 MockLLM、结果会一致，仅用于验证链路——docstring 与 README
都说明真实对比需配置两个真实端点后重跑。结果写 eval_run（run_tag=before/after）。
"""
from __future__ import annotations

import json
import os

from shopmind import db
from shopmind.ai import get_llm
from shopmind.ai.llm import OpenAICompatLLM
from shopmind.config import get_settings
from shopmind.logging import get_logger

from . import eval_sets
from .build_dataset import SYSTEM_PROMPT
from .judge import judge_compliance, judge_humanize

log = get_logger("p5.eval_before_after")


def _make_client(kind: str) -> tuple:
    """构造回答端点，返回 (client, model_name, fallback)。

    - kind='base'：直接用 get_llm()；
    - kind='finetuned'：读 LLM_FINETUNED_* 环境变量构造微调端点；三者都没配则回退 get_llm()；
    - mock 模式下两者都是 MockLLM。
    """
    s = get_settings()
    if s.use_mock:
        return get_llm(), s.llm_model, False

    if kind == "finetuned":
        base_url = os.getenv("LLM_FINETUNED_BASE_URL")
        api_key = os.getenv("LLM_FINETUNED_API_KEY")
        model = os.getenv("LLM_FINETUNED_MODEL")
        if base_url and api_key and model:
            return OpenAICompatLLM(base_url, api_key, model, s.llm_temperature), model, False
        log.info("未配置 LLM_FINETUNED_*，finetuned 端点回退到 base get_llm()")
        return get_llm(), s.llm_model, True

    return get_llm(), s.llm_model, False


def run_eval(kind: str) -> dict:
    """用指定端点逐条生成回答并打分，返回 {humanize_avg, compliance_avg, n, model, fallback}。"""
    client, model, fallback = _make_client(kind)

    humanize_scores: list[int] = []
    for item in eval_sets.HUMANIZE_SET:
        ans = client.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": item["question"]},
            ]
        )
        humanize_scores.append(judge_humanize(item["question"], ans))

    compliance_scores: list[int] = []
    for item in eval_sets.COMPLIANCE_SET:
        ans = client.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": item["question"]},
            ]
        )
        compliance_scores.append(judge_compliance(item["question"], ans))

    return {
        "humanize_avg": round(sum(humanize_scores) / len(humanize_scores), 2) if humanize_scores else 0.0,
        "compliance_avg": round(sum(compliance_scores) / len(compliance_scores), 2) if compliance_scores else 0.0,
        "n": len(humanize_scores) + len(compliance_scores),
        "model": model,
        "fallback": fallback,
    }


def _write_runs(run_tag: str, metrics: dict) -> None:
    """把一次 run 的指标写入 eval_run（两个评测集各写一行，run_tag=before/after）。"""
    config = json.dumps({"fallback": metrics.get("fallback", False)}, ensure_ascii=False)
    payload = json.dumps(metrics, ensure_ascii=False)
    for name in ("p5_humanize", "p5_compliance"):
        try:
            did = db.fetchone("SELECT id FROM eval_dataset WHERE name=:n", {"n": name})
            if not did:
                continue
            db.insert_get_id(
                "INSERT INTO eval_run (dataset_id, model, run_tag, config_json, metrics_json) "
                "VALUES (:d, :m, :t, :c, :j)",
                {"d": int(did["id"]), "m": metrics["model"], "t": run_tag,
                 "c": config, "j": payload},
            )
        except Exception as e:  # noqa: BLE001
            log.warning("写 eval_run 失败（%s）：%s", name, e)


def run_compare() -> dict:
    """跑 base 与 finetuned 两遍，写 eval_run，返回 {before: {...}, after: {...}}。"""
    before = run_eval("base")
    after = run_eval("finetuned")
    _write_runs("before", before)
    _write_runs("after", after)
    log.info("before/after 对比：%s", json.dumps({"before": before, "after": after}, ensure_ascii=False))
    return {"before": before, "after": after}

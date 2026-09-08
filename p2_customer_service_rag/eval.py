"""P2 评测：检索命中 / 拒答准确率 / 生成质量（忠实度 + 相关性）。

三套评测集 + 自研打分（可选接 RAGAS）：
  - retrieval：query → 期望命中的文档标题，算 hit@k / MRR；
  - refusal：域内应答 vs 域外应拒，算 answerability 准确率；
  - rag：LLM 判官打分（忠实度 / 相关性），mock 下用启发式回退。
结果写回 eval_dataset / eval_item / eval_run（回血中台）。
"""
from __future__ import annotations

import json

from shopmind import db
from shopmind.ai import get_llm
from shopmind.config import get_settings
from shopmind.logging import get_logger
from shopmind.text import tokenize

from .pipeline import analyze, answer

log = get_logger("p2.eval")

# (query, 期望命中的知识文档标题)。ground_truth 严格对齐 P1 种子的 6 篇知识文档标题。
RETRIEVAL_SET = [
    ("你们支持无理由退货吗", "退换货政策"),
    ("签收后发现质量问题能退换吗", "退换货政策"),
    ("退货的运费谁来出", "退换货政策"),
    ("保修期是多久", "保修服务条款"),
    ("保修期内维修要收费吗", "保修服务条款"),
    ("哪些情况不在保修范围", "保修服务条款"),
    ("几天能发货", "物流配送说明"),
    ("你们用什么快递配送", "物流配送说明"),
    ("偏远地区能不能送到", "物流配送说明"),
    ("音箱怎么连接WiFi配网", "小音智能音箱 Pro 使用手册（节选）"),
    ("音箱的语音唤醒词是什么", "小音智能音箱 Pro 使用手册（节选）"),
    ("音箱怎么打开蓝牙", "小音智能音箱 Pro 使用手册（节选）"),
    ("怎么开电子发票", "发票说明"),
    ("电子发票多久能收到", "发票说明"),
    ("你们怎么保护我的个人信息", "隐私与数据保护"),
]

REFUSAL_IN_SCOPE = [
    "支持7天无理由退货吗",
    "退款多久到账",
    "充电宝可以带上飞机吗",
    "扫地机器人续航多久",
    "多久发货",
    "电子发票怎么开",
]

REFUSAL_OUT_SCOPE = [
    "今天北京的天气怎么样",
    "帮我写一首关于春天的诗",
    "推荐几只值得买的股票",
    "怎么做红烧肉",
    "最近有什么好看的电影",
    "帮我写一封辞职信",
]

RAG_SET = [
    "支持7天无理由退货吗",
    "退款多久到账",
    "音箱怎么配网",
    "充电宝可以带上飞机吗",
    "扫地机器人续航多久",
    "电子发票怎么开",
]


def _ensure_dataset(name: str, dtype: str, items: list[tuple]) -> int:
    existing = db.fetchone("SELECT id FROM eval_dataset WHERE name=:n", {"n": name})
    if existing:
        did = int(existing["id"])
        db.execute("DELETE FROM eval_item WHERE dataset_id=:d", {"d": did})
    else:
        did = db.insert_get_id(
            "INSERT INTO eval_dataset (name, dataset_type, description) VALUES (:n, :t, :d)",
            {"n": name, "t": dtype, "d": f"P2 评测集：{dtype}"},
        )
    for q, gt in items:
        db.execute(
            "INSERT INTO eval_item (dataset_id, question, ground_truth) VALUES (:d, :q, :g)",
            {"d": did, "q": q, "g": gt},
        )
    db.execute("UPDATE eval_dataset SET size=:s WHERE id=:d", {"s": len(items), "d": did})
    return did


def build_datasets() -> dict:
    ids = {
        "retrieval": _ensure_dataset("p2_retrieval", "retrieval", RETRIEVAL_SET),
        "refusal_in": _ensure_dataset("p2_refusal_in", "refusal", [(q, "in") for q in REFUSAL_IN_SCOPE]),
        "refusal_out": _ensure_dataset("p2_refusal_out", "refusal", [(q, "out") for q in REFUSAL_OUT_SCOPE]),
        "rag": _ensure_dataset("p2_rag", "rag", [(q, "") for q in RAG_SET]),
    }
    log.info("评测集已就绪：%s", json.dumps(ids, ensure_ascii=False))
    return ids


def run_retrieval_eval(k: int = 3) -> dict:
    hits = {1: 0, 3: 0}
    rr_sum = 0.0
    n = len(RETRIEVAL_SET)
    for query, expected in RETRIEVAL_SET:
        res = analyze(query)  # 纯检索，不调 LLM（快）
        titles = [s["title"] for s in res["sources"]]
        # 找期望标题首次命中位置
        rank = next((i + 1 for i, t in enumerate(titles) if t == expected), None)
        if rank:
            if rank == 1:
                hits[1] += 1
            if rank <= 3:
                hits[3] += 1
            rr_sum += 1.0 / rank
    return {
        "hit@1": round(hits[1] / n, 4),
        "hit@3": round(hits[3] / n, 4),
        "mrr": round(rr_sum / n, 4),
        "n": n,
    }


def run_refusal_eval() -> dict:
    correct = 0
    total = 0
    for q in REFUSAL_IN_SCOPE:
        r = analyze(q)  # 纯检索，不调 LLM（快）
        total += 1
        correct += 1 if r["answerable"] else 0
    for q in REFUSAL_OUT_SCOPE:
        r = analyze(q)
        total += 1
        correct += 1 if not r["answerable"] else 0
    return {"refusal_accuracy": round(correct / total, 4), "n": total}


def _judge_faithfulness(question: str, contexts: list[str], ans: str) -> float:
    if get_settings().use_mock:
        ctx = set(tokenize(" ".join(contexts)))
        a = set(tokenize(ans))
        ratio = len(a & ctx) / len(a) if a else 0.0
        return 1.0 if ratio >= 0.4 else 0.0
    prompt = (
        "判断回答是否完全基于给定的参考知识（忠实度）。只输出 JSON：{\"faithful\": true 或 false}\n"
        f"问题：{question}\n参考知识：\n{chr(10).join(contexts)}\n回答：{ans}"
    )
    resp = get_llm().chat([{"role": "user", "content": prompt}])
    return 1.0 if "true" in resp.lower() else 0.0


def _judge_relevance(question: str, ans: str) -> float:
    if get_settings().use_mock:
        q = set(tokenize(question))
        a = set(tokenize(ans))
        ratio = len(q & a) / len(q) if q else 0.0
        return 1.0 if ratio >= 0.3 else 0.0
    prompt = (
        "判断回答是否切题、直接回答了问题（相关性）。只输出 JSON：{\"relevant\": true 或 false}\n"
        f"问题：{question}\n回答：{ans}"
    )
    resp = get_llm().chat([{"role": "user", "content": prompt}])
    return 1.0 if "true" in resp.lower() else 0.0


def run_rag_eval() -> dict:
    faith, rel = [], []
    for q in RAG_SET:
        res = answer(q, use_cache=False)
        contexts = [s["title"] + " " + s.get("content", "") for s in res["sources"]]
        faith.append(_judge_faithfulness(q, contexts, res["answer"]))
        rel.append(_judge_relevance(q, res["answer"]))
    return {
        "faithfulness": round(sum(faith) / len(faith), 4),
        "relevance": round(sum(rel) / len(rel), 4),
        "n": len(RAG_SET),
    }


def run_all(do_rag: bool = False) -> dict:
    """跑评测。默认只跑 检索 + 拒答（纯检索、快）；do_rag=True 再加 LLM 判官（慢，受云端限流影响）。"""
    build_datasets()
    metrics = {
        "retrieval": run_retrieval_eval(),
        "refusal": run_refusal_eval(),
        "model": get_settings().llm_model,
        "provider": get_settings().ai_provider,
    }
    if do_rag:
        metrics["rag"] = run_rag_eval()
    did = db.fetchone("SELECT id FROM eval_dataset WHERE name='p2_rag'")
    db.insert_get_id(
        "INSERT INTO eval_run (dataset_id, model, run_tag, metrics_json) VALUES (:d, :m, 'baseline', :j)",
        {"d": int(did["id"]) if did else 0, "m": metrics["model"], "j": json.dumps(metrics, ensure_ascii=False)},
    )
    log.info("P2 评测结果：%s", json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics

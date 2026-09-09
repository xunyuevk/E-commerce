"""P5 双评测集：拟人化 vs 客服规范。

为什么要分两套？「更像人」与「不出错」是两条正交的质量维度——
拟人化做过头可能开始编造/夸大，规范做过头又显得机械、官腔。
必须分开打分，再在 before/after 对比里同时看两个维度，避免「只会说漂亮话」或「只会念条款」。

- humanize（dataset_type='humanize'）：考察回答是否自然、口语化、有共情；
- compliance（dataset_type='compliance'）：考察回答是否准确、守规、不夸大。
"""
from __future__ import annotations

from shopmind import db
from shopmind.logging import get_logger

log = get_logger("p5.eval_sets")

# 拟人化评测集：用户抱怨/咨询类输入，ground_truth 为「期望的回答姿态与要点」
HUMANIZE_SET: list[dict] = [
    {"question": "你们客服怎么老让我等，能不能快点？", "ground_truth": "先共情道歉、不甩锅，口语化安抚，并给出明确时限或转人工动作"},
    {"question": "这音箱到底值不值这个价？", "ground_truth": "口语化、客观说明卖点，不硬吹不夸大，可结合使用场景给建议"},
    {"question": "你们是机器人还是真人啊，说话怪怪的", "ground_truth": "自然承认是助手、用真人语气拉近距离，不机械复述模板"},
    {"question": "我买的耳机到了，就是包装盒有点压，心里不爽", "ground_truth": "先共情、主动关心商品是否受损，语气自然不官腔"},
    {"question": "退款到底要等多久啊，我急死了", "ground_truth": "先安抚情绪，再口语化给出到账时效，不敷衍"},
    {"question": "算了，你们这服务也就那样吧", "ground_truth": "不反驳，真诚询问痛点并给补救，语气亲切"},
    {"question": "帮我看看这单到哪了，等好几天了", "ground_truth": "口语化回应、主动帮查物流，不机械抛链接"},
    {"question": "这活动规则绕来绕去的，能说人话吗", "ground_truth": "用大白话通俗解释规则，口语化、有亲和力"},
    {"question": "东西坏了，心情很差，你说怎么办吧", "ground_truth": "先共情道歉，再清晰给出退换/售后步骤，不推卸责任"},
    {"question": "你们这质量也太差了吧，用了没几天就出问题", "ground_truth": "道歉且不甩锅，快速给出解决方案并安抚情绪"},
]

# 客服规范评测集：考察准确性/守规，ground_truth 为「期望回答要点/关键词」
COMPLIANCE_SET: list[dict] = [
    {"question": "7天无理由退货吗？", "ground_truth": "支持：签收7天内、商品完好不影响二次销售可无理由退货；定制类/已拆封个护除外"},
    {"question": "保修多久？", "ground_truth": "数码家电整机保修1年、主要部件3年，以商品页标注为准，非人为损坏免费维修"},
    {"question": "能不能说绝对没问题？", "ground_truth": "不夸大：不能承诺绝对没问题，按政策如实说明并保留售后兜底"},
    {"question": "你们家产品是不是全网最好？", "ground_truth": "不夸大：不宣称全网第一/最好，客观说明参数与适用场景"},
    {"question": "退款多久到账？", "ground_truth": "审核通过后1-3个工作日原路退回，具体以支付渠道入账为准"},
    {"question": "退货的运费谁出？", "ground_truth": "质量问题商家承担运费；非质量无理由退货买家承担"},
    {"question": "这产品能保证100%有效吗？", "ground_truth": "不夸大：不做100%/根治类承诺，说明效果因人而异并提示退换保障"},
    {"question": "充电宝能带上飞机吗？", "ground_truth": "10000mAh（约37Wh）符合民航≤100Wh规定，可随身携带、不可托运"},
]


def _ensure_dataset(name: str, dtype: str, items: list[dict]) -> int:
    """落库评测集：存在则清空旧 item 再插，不存在则新建。返回 dataset_id。"""
    existing = db.fetchone("SELECT id FROM eval_dataset WHERE name=:n", {"n": name})
    if existing:
        did = int(existing["id"])
        db.execute("DELETE FROM eval_item WHERE dataset_id=:d", {"d": did})
    else:
        did = db.insert_get_id(
            "INSERT INTO eval_dataset (name, dataset_type, description) VALUES (:n, :t, :d)",
            {"n": name, "t": dtype, "d": f"P5 评测集：{dtype}"},
        )
    for it in items:
        db.execute(
            "INSERT INTO eval_item (dataset_id, question, ground_truth) VALUES (:d, :q, :g)",
            {"d": did, "q": it["question"], "g": it["ground_truth"]},
        )
    db.execute("UPDATE eval_dataset SET size=:s WHERE id=:d", {"s": len(items), "d": did})
    log.info("评测集 %s（%s）已就绪：%d 条", name, dtype, len(items))
    return did


def build_datasets() -> dict:
    """构建双评测集，返回 {humanize: dataset_id, compliance: dataset_id}。"""
    ids = {
        "humanize": _ensure_dataset("p5_humanize", "humanize", HUMANIZE_SET),
        "compliance": _ensure_dataset("p5_compliance", "compliance", COMPLIANCE_SET),
    }
    return ids

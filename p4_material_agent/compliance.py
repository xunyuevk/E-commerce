"""合规双通道：确定性规则引擎（第一通道）+ LLM 语义复核（第二通道）。

第一通道（规则引擎）：RULE_BANNED_WORDS 命中即 fail，确定、可解释、零成本、零延迟，
  负责拦截广告法 / 医疗广告里的"硬雷区"（绝对化、夸大、医疗疗效用语）。
第二通道（LLM 复核）：规则引擎只认"字面词"，拦不住"语义上的夸大/绝对化"
  （例如"用了都说好"没命中任何词但同样违规），因此用 LLM 做语义兜底。
  真实模式让模型只输出 pass|fail|review；mock 模式走确定性启发式（见 llm_check docstring）。

组合策略（combined_check）：先规则后 LLM，任一 fail 则 fail——规则命中即硬拒绝，
规则通过才交 LLM，其 verdict 直接决定 pass/review/fail。
"""
from __future__ import annotations

from shopmind.ai import get_llm
from shopmind.config import get_settings

# 绝对化 / 夸大 / 医疗化用语（广告法敏感词）
RULE_BANNED_WORDS: tuple[str, ...] = (
    "最好", "第一", "顶级", "国家级", "世界级",
    "全网最低", "史上最低",
    "根治", "治愈", "包治", "抗癌",
    "100%", "绝对", "零风险", "无效退款",
)

# mock 启发式里的"强禁止词"（医疗疗效 / 绝对承诺）：命中即 fail；
# 其余词（如"最好/第一"这类夸大但非绝对）在 mock 下无法做语境判断，判 pass，
# review 的裁决场景留给真实 LLM（见 llm_check docstring）。
STRONG_BANNED_WORDS: frozenset[str] = frozenset({
    "全网最低", "史上最低",
    "根治", "治愈", "包治", "抗癌",
    "100%", "绝对", "零风险", "无效退款",
})


def rule_check(text: str) -> tuple[bool, list[str]]:
    """第一通道：确定性规则引擎。

    返回 (是否合规, 命中词列表)。命中任意 RULE_BANNED_WORDS 即不合规（fail）。
    采用子串匹配，命中顺序与词表一致，结果确定可复现。
    """
    hits: list[str] = []
    for word in RULE_BANNED_WORDS:
        if word in text:
            hits.append(word)
    return (len(hits) == 0, hits)


def llm_check(text: str) -> str:
    """第二通道：LLM 语义复核，返回 pass | fail | review。

    mock 模式：确定性启发式——复用 rule_check，命中"强禁止词"返回 fail，否则 pass；
      之所以"否则 pass"而非"review"，是因为 mock 无真实语义判断能力，
      而第一通道已兜住字面词，mock 下 review 应由真实 LLM 在语义层面给出。
    真实模式：get_llm().chat 让模型只输出 pass/fail/review（prompt 强约束）。
    """
    if get_settings().use_mock:
        _ok, hits = rule_check(text)
        if any(w in STRONG_BANNED_WORDS for w in hits):
            return "fail"
        return "pass"

    prompt = (
        "你是电商广告合规审核员。判断下面这段营销文案是否违反广告法"
        "（绝对化用语、夸大宣传、医疗疗效承诺等）。\n"
        "只输出一个词：pass（合规）/ fail（违规）/ review（存疑需人工）。\n\n"
        f"文案：\n{text}"
    )
    raw = get_llm().chat([{"role": "user", "content": prompt}]).strip().lower()
    if raw not in ("pass", "fail", "review"):
        # 模型未按约束输出时，安全兜底为 review（转人工），避免漏放违规
        return "review"
    return raw


def combined_check(text: str) -> tuple[str, list[str]]:
    """双通道合并：先规则后 LLM，任一 fail 则 fail。

    返回 (compliance, 命中词)，compliance ∈ {pass, fail, review}。
      规则命中 → 立即 fail（确定性硬门禁，不依赖模型）；
      规则通过 → 交 LLM 复核，其 verdict 直接决定 pass/review/fail。
    """
    ok, hits = rule_check(text)
    if not ok:
        return "fail", hits
    verdict = llm_check(text)
    if verdict == "fail":
        return "fail", hits
    return verdict, hits

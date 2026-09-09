"""P5 LLM 判官：拟人化打分与规范打分（0~5 整数）。

真实模式用 get_llm() 让模型只输出一个 0-5 数字；mock 模式用确定性启发式，
保证离线（无 API Key）也能跑通 before/after 对比链路。
"""
from __future__ import annotations

import re

from shopmind.ai import get_llm
from shopmind.config import get_settings
from shopmind.logging import get_logger

log = get_logger("p5.judge")

# mock 下判断「拟人化程度」的口语词/语气词
_SPOKEN = ("呢", "哦", "呀", "哈", "啦", "亲", "喔", "嘛")
# mock 下判断「是否夸大承诺」的夸大词
_EXAGGERATION = ("最好", "绝对", "100%", "根治", "第一")


def _has_emoji(text: str) -> bool:
    """粗略判断是否含 emoji（覆盖常用 Unicode emoji 区间）。"""
    return any(
        0x1F000 <= ord(ch) <= 0x1FAFF
        or 0x2600 <= ord(ch) <= 0x27BF
        or 0x2B00 <= ord(ch) <= 0x2BFF
        or 0xFE00 <= ord(ch) <= 0xFE0F
        for ch in text
    )


def _parse_score(raw: str) -> int:
    """从模型输出解析 0-5 整数，解析失败回退 2。"""
    raw = (raw or "").strip()
    try:
        score = int(raw)
    except ValueError:
        m = re.search(r"\d", raw)
        score = int(m.group()) if m else 2
    return max(0, min(5, score))


def judge_humanize(question: str, answer: str) -> int:
    """按「自然度 / 口语化 / 共情」给 0~5 分。"""
    if get_settings().use_mock:
        text = answer or ""
        if text.strip().startswith("[mock]"):
            return 2
        if _has_emoji(text) or any(w in text for w in _SPOKEN):
            return 4
        return 3

    prompt = (
        "你是客服回答质量评审。请从「自然度、口语化、共情」三个维度，"
        "给下面这条客服回答打 0~5 的整数分（5=非常自然有温度，0=机械冷漠）。"
        "只输出一个 0-5 的整数，不要任何解释。\n"
        f"用户问题：{question}\n客服回答：{answer}\n分数："
    )
    try:
        resp = get_llm().chat([{"role": "user", "content": prompt}])
        return _parse_score(resp)
    except Exception as e:  # noqa: BLE001
        log.warning("judge_humanize 判官调用失败，回退 2：%s", e)
        return 2


def judge_compliance(question: str, answer: str) -> int:
    """按「是否准确、是否夸大」给 0~5 分。"""
    if get_settings().use_mock:
        text = answer or ""
        if any(w in text for w in _EXAGGERATION):
            return 1
        return 3

    prompt = (
        "你是客服回答合规评审。请判断下面这条客服回答是否「准确、守规、不夸大」，"
        "打 0~5 的整数分（5=完全准确守规，0=明显夸大/编造政策/错误承诺）。"
        "只输出一个 0-5 的整数，不要任何解释。\n"
        f"用户问题：{question}\n客服回答：{answer}\n分数："
    )
    try:
        resp = get_llm().chat([{"role": "user", "content": prompt}])
        return _parse_score(resp)
    except Exception as e:  # noqa: BLE001
        log.warning("judge_compliance 判官调用失败，回退 2：%s", e)
        return 2

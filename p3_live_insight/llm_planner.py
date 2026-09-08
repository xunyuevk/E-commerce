"""P3 LLM 规划切分：LLM 看全文、按"大主题"切分成若干大段。

设计（面试可讲，与 P4 同哲学——LLM 做语义、确定性代码做精确）：
  - 一次把全文字面交给 LLM，让它按「几个大主题」切段，而非逐句判断——
    避免语义小转折也被切成一段，导致段数失控；
  - 提示词显式约束段数（默认 3~5 段）+ 明确"切大段、不要过细"；
  - LLM 只输出 end_idx（各段结束句序号，严格递增、末段到末尾），不做秒数；
    时间戳由代码从 ASR 字级时间戳映射，天然连续不重叠；
  - 结构化输出 + 容错解析 + 自纠重试（复用 P4 经验）。

入参：clauses = [{index, start_sec, end_sec, text}, ...]，requirement = 用户需求文本。
出参：list[dict]，每项 {topic, start_idx, end_idx}（1-based，含两端）。
"""
from __future__ import annotations

import json

from shopmind.ai import get_llm
from shopmind.logging import get_logger

log = get_logger("shopmind.p3.llm_planner")

_JSON_RULE = (
    "只输出一个合法的 JSON 对象，形如 {\"segments\":[...]}，不要任何解释、前后缀或 markdown 代码块。"
    "segments 是数组，每个元素含 topic(字符串) 和 end_idx(整数，本段最后一句话的序号)。"
)


def _default_seg_count(n: int) -> int:
    """默认段数：句子多则允许稍多，但收敛在 3~5 大段。"""
    return 4 if n <= 33 else 5


def build_prompt(clauses: list[dict], requirement: str, seg_count: int) -> str:
    lines = [f"{c['index']}. {c['text']}" for c in clauses]
    transcript_block = "\n".join(lines)
    n = len(clauses)
    return (
        f"下面是一段直播带货视频的逐句转写（每行开头是句子序号，共 {n} 句）：\n\n"
        f"{transcript_block}\n\n"
        f"用户需求：{requirement}\n\n"
        f"请把这段视频按【几个大主题】切成 {seg_count} 大段（每段主题要有明显差异，是内容的大块划分，"
        f"不要切得过细）。每个片段只需给出它的【最后一句话的序号 end_idx】，第一段从第 1 句开始，"
        f"后续每段紧接着上一段之后。\n"
        f"例如切成 3 段可输出：{{\"segments\":[{{\"topic\":\"开场\",\"end_idx\":8}},"
        f"{{\"topic\":\"起号\",\"end_idx\":20}},{{\"topic\":\"选品与裂变\",\"end_idx\":{n}}}]}}。\n"
        f"要求：\n"
        f"1. end_idx 必须是【整数句子序号】，且最后一段的 end_idx 必须等于 {n}；\n"
        f"2. end_idx 严格递增；\n"
        f"3. 每段给一个简短主题 topic（不超过 8 字）；\n"
        f"4. 段数严格等于 {seg_count} 段。\n"
        f"{_JSON_RULE}"
    )


def _parse_json(raw: str) -> list[dict] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        pass
    if data is None:
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = text.find(open_c)
            end = text.rfind(close_c)
            if start != -1 and end > start:
                try:
                    data = json.loads(text[start : end + 1])
                    break
                except json.JSONDecodeError:
                    continue
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        segs = data.get("segments")
        if isinstance(segs, list):
            return segs
    return None


def _to_int(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        try:
            return int(float(v.strip()))
        except ValueError:
            return None
    return None


def _validate(plan: list[dict], n: int, seg_count: int) -> list[dict] | None:
    """校验：end_idx 严格递增、首段从 1 起、末段到 n、段数 == seg_count。"""
    if len(plan) != seg_count:
        return None
    normalized = []
    prev_end = 0
    for item in plan:
        if not isinstance(item, dict):
            return None
        e = _to_int(item.get("end_idx"))
        if e is None:
            return None
        if e <= prev_end or e > n:
            return None
        normalized.append({"topic": str(item.get("topic") or "未命名"), "start_idx": prev_end + 1, "end_idx": e})
        prev_end = e
    return normalized if prev_end == n else None


def plan_segments(clauses: list[dict], requirement: str, seg_count: int | None = None) -> list[dict]:
    """LLM 规划切分：返回 [{topic, start_idx, end_idx}, ...]（1-based），共 seg_count 段。"""
    llm = get_llm()
    n = len(clauses)
    seg_count = seg_count or _default_seg_count(n)
    prompt = build_prompt(clauses, requirement, seg_count)

    for attempt in range(3):
        raw = llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        plan = _parse_json(raw)
        if plan is not None:
            valid = _validate(plan, n, seg_count)
            if valid is not None:
                return valid
            log.warning("LLM 分段计划校验失败（第 %d 次）：%s", attempt + 1, raw[:200])
        else:
            log.warning("LLM 输出非合法 JSON（第 %d 次）：%s", attempt + 1, raw[:200])
        prompt = (
            prompt
            + "\n\n你上次的输出不合法。请重新只输出 {\"segments\":[...]} 对象，"
            f"恰好 {seg_count} 段，end_idx 为严格递增的整数句子序号，最后一段 end_idx 必须等于 {n}。"
        )
    raise RuntimeError("LLM 分段规划连续失败，无法产出合法计划")

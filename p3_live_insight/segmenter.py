"""P3 语义分段器：把直播转写文本切成「商品介绍」粒度的片段。

设计（面试可讲）：
  - 离线确定性：不依赖 LLM，用「商品名 / 关键词」做边界判断，结果可复现、零成本；
  - 边界语义：只有当主播开始介绍一个新商品时才切段（粉丝提问不切段），
    未命中商品的段归为「互动/其他」；
  - 时间轴：start_sec / end_sec 从转写时间戳解析，天然对齐视频切片位置。
"""
from __future__ import annotations

import re

from shopmind.ai import get_llm
from shopmind.config import get_settings

# 商品名 → 关键词（优先级即列表顺序，长关键词在前避免误命中）
PRODUCT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("小音智能音箱 Pro", ("小音智能音箱", "智能音箱", "音箱")),
    ("扫地机器人 S1", ("扫地机器人",)),
    ("空气炸锅 5L", ("空气炸锅",)),
    ("真无线蓝牙耳机 X", ("真无线蓝牙耳机", "蓝牙耳机")),
    ("10000mAh 快充充电宝", ("快充充电宝", "充电宝")),
    ("316 不锈钢保温杯", ("不锈钢保温杯", "保温杯")),
]

OTHER_TOPIC = "互动/其他"

# 转写行形如：MM:SS 角色：内容（分钟:秒，可选小时在前）
_LINE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([^：:\s]{1,10})\s*[：:]\s*(.*)$")

# 摘要/情感前先剥掉角色前缀，避免「主播：」这类噪声词参与判断
_ROLE_RE = re.compile(r"^(?:主播|助播|观众|粉丝|用户)\s*[：:]\s*", flags=re.M)

# 简单情感词典
_NEG_WORDS = ("差", "坏", "问题", "投诉", "贵")
_POS_WORDS = ("好", "不错", "划算", "推荐", "放心")

_SENT_SPLIT = re.compile(r"[。！？!?]")


def _parse_lines(transcript: str) -> list[tuple[int, str, str]]:
    """解析转写文本，返回 [(秒数, 角色, 内容), ...]，跳过无法识别的行。"""
    parsed: list[tuple[int, str, str]] = []
    for line in transcript.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        minute = int(m.group(1))
        second = int(m.group(2))
        parsed.append((minute * 60 + second, m.group(3), m.group(4)))
    return parsed


def _match_topics(text: str) -> list[str]:
    """按关键词优先级返回文本中命中的商品 topic（一个商品只返回一次）。"""
    hits: list[str] = []
    for topic, keywords in PRODUCT_KEYWORDS:
        if any(k in text for k in keywords):
            hits.append(topic)
    return hits


def _finalize(cur: dict, segments: list[dict]) -> None:
    """把当前段收口：transcript 合并为多行文本、补 seq 后入列表。"""
    cur["transcript"] = "\n".join(cur["transcript"])
    cur["seq"] = len(segments) + 1
    segments.append(cur)


def segment(transcript: str) -> list[dict]:
    """语义分段：主播开始介绍新商品即切段，未命中商品归为「互动/其他」。

    返回 list[dict]，每项含 seq / start_sec / end_sec / transcript / topic。
    """
    parsed = _parse_lines(transcript)
    segments: list[dict] = []
    cur: dict | None = None

    for sec, speaker, text in parsed:
        hits = _match_topics(text)
        new_topic: str | None = None
        # 只有主播/助播开口介绍新商品才作为边界；粉丝提问不切段
        if speaker in ("主播", "助播"):
            cur_topic = cur["topic"] if cur is not None else None
            for t in hits:
                if t != cur_topic:
                    new_topic = t
                    break

        if new_topic is not None:
            if cur is not None:
                _finalize(cur, segments)
            cur = {
                "start_sec": sec,
                "end_sec": sec,
                "transcript": [f"{speaker}：{text}"],
                "topic": new_topic,
            }
        else:
            if cur is None:
                cur = {
                    "start_sec": sec,
                    "end_sec": sec,
                    "transcript": [],
                    "topic": OTHER_TOPIC,
                }
            cur["transcript"].append(f"{speaker}：{text}")
            cur["end_sec"] = sec

    if cur is not None:
        _finalize(cur, segments)
    return segments


def _strip_roles(text: str) -> str:
    """去掉每行开头的「角色：」前缀，得到纯净口播内容。"""
    return _ROLE_RE.sub("", text).strip()


def _extractive_summary(text: str, max_sentences: int = 2, max_len: int = 100) -> str:
    """抽取式摘要：取前 1~2 句并裁剪，离线确定性、零成本。"""
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    if not parts:
        return text.strip()[:max_len]
    summary = "。".join(parts[:max_sentences])
    if len(summary) > max_len:
        summary = summary[:max_len] + "…"
    return summary


def summarize(segment_text: str, topic: str) -> str:
    """生成段摘要：mock 取前 1~2 句裁剪，真实模式调 LLM 生成式摘要。"""
    clean = _strip_roles(segment_text)
    if get_settings().use_mock:
        return _extractive_summary(clean)
    llm = get_llm()
    prompt = f"请用一句话概括下面这段「{topic}」直播切片的核心卖点，口语化、不超过 40 字：\n{clean}"
    return llm.chat([{"role": "user", "content": prompt}])


def sentiment(segment_text: str) -> str:
    """简单规则情感：命中负面词 → negative，正面词 → positive，否则 neutral。

    先剔除「没问题 / 没有问题 / 毫无问题」这类否定式，避免「问题」被误判为负面。
    """
    clean = _strip_roles(segment_text)
    clean = clean.replace("没问题", "").replace("没有问题", "").replace("毫无问题", "")
    if any(w in clean for w in _NEG_WORDS):
        return "negative"
    if any(w in clean for w in _POS_WORDS):
        return "positive"
    return "neutral"

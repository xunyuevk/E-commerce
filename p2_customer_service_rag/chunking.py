"""P2 切片策略：段落感知的固定窗口切片 + FAQ 单条切片。

选型（面试可讲）：
  - 政策/手册类用「段落打包 + 重叠窗口」，避免把一句话从中间切断；
  - FAQ 天然是 Q&A 对，整条成块，比机械切更保语义；
  - 参数 chunk_size / overlap 通过 chunk 实验（检索命中率）来定，不是拍脑袋。
"""
from __future__ import annotations


def _split_units(text: str) -> list[str]:
    """把文本切成段落单元：按标题/空行优先切。"""
    # 标题行单独成单元
    units: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if buf:
                units.append("\n".join(buf))
                buf = []
            continue
        if s.startswith("#"):
            if buf:
                units.append("\n".join(buf))
                buf = []
            units.append(s)
        else:
            buf.append(s)
    if buf:
        units.append("\n".join(buf))
    return [u for u in units if u.strip()]


def chunk_by_paragraphs(text: str, max_chars: int = 500, overlap_chars: int = 50) -> list[str]:
    """段落感知打包成不超过 max_chars 的切片，带 overlap。"""
    units = _split_units(text)
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for u in units:
        # 单个超长单元硬切
        if len(u) > max_chars:
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            chunks.append(u[:max_chars])
            continue
        if cur_len + len(u) + 1 > max_chars and cur:
            chunks.append("\n".join(cur))
            # overlap：保留上一块尾部 overlap_chars 作为新块前缀
            tail = chunks[-1][-overlap_chars:] if overlap_chars else ""
            cur = [tail] if tail else []
            cur_len = len(tail)
        cur.append(u)
        cur_len += len(u) + 1
    if cur:
        chunks.append("\n".join(cur))
    return [c for c in chunks if c.strip()]


def chunk_faq(question: str, answer: str) -> str:
    """FAQ 单条成块。"""
    return f"Q: {question}\nA: {answer}"

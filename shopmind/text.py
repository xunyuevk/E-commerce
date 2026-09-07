"""文本工具：jieba 中文分词。

关键设计（面试可讲）：
  - 不在 ES 里装 ik 插件，而是入库时用 jieba 预分词写入 content_tokens 字段，
    ES 侧用 whitespace analyzer 做 BM25 —— 开发期免插件、分词逻辑可控；
  - 生产可切 ik_max_word，只需改 mapping + 重灌，BM25/向量检索代码不变。
"""
from __future__ import annotations

import logging

import jieba

# jieba 首次加载词典会打印日志，静音
jieba.setLogLevel(logging.WARNING)


def tokenize(text: str) -> list[str]:
    """中文分词，返回小写 token 列表。"""
    if not text:
        return []
    return [t.strip() for t in jieba.lcut(text.lower()) if t.strip()]


def join_tokens(text: str) -> str:
    """分词后用空格连接，供 ES whitespace analyzer 使用。"""
    return " ".join(tokenize(text))

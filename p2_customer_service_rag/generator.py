"""P2 生成：RAG 提示词组装 + LLM 调用。"""
from __future__ import annotations

from shopmind.ai import get_llm

SYSTEM_PROMPT = (
    "你是 ShopMind 电商客服助手。请严格基于给定的参考知识回答用户问题，"
    "不要编造知识中没有的信息；若知识不足以回答，请明确说明无法回答并建议联系人工客服。"
    "回答要准确、简洁、口语化。"
)


def build_messages(query: str, contexts: list[str]) -> list[dict]:
    context_block = "\n\n".join(f"【参考 {i + 1}】\n{c}" for i, c in enumerate(contexts))
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"参考知识：\n{context_block}\n\n用户问题：{query}\n\n请基于参考知识回答。"},
    ]


def generate(query: str, contexts: list[str]) -> str:
    return get_llm().chat(build_messages(query, contexts))

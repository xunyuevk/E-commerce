"""对话模型：DeepSeek / Qwen / SiliconFlow（OpenAI 兼容）+ mock 回退。"""
from __future__ import annotations

from ..config import get_settings
from ..logging import get_logger
from .base import ChatLLM, post_with_retry

log = get_logger("shopmind.ai.llm")

DEFAULT_SYSTEM = "你是 ShopMind 电商客服助手，回答准确、简洁、口语化，不确定时明确说明。"


class OpenAICompatLLM:
    """OpenAI 兼容 Chat Completions 客户端（DeepSeek/Qwen/SiliconFlow 通用）。"""

    def __init__(self, base_url: str, api_key: str, model: str, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def chat(self, messages: list[dict], **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": False,
        }
        if kwargs.get("max_tokens"):
            payload["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("response_format"):
            payload["response_format"] = kwargs["response_format"]
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        resp = post_with_retry(url, json=payload, headers=headers, timeout=60)
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class MockLLM:
    """离线回退：返回确定性的占位回答，明确标注 mock，避免与真实结果混淆。"""

    def chat(self, messages: list[dict], **kwargs) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        head = (last_user or "").strip().replace("\n", " ")[:80]
        return f"[mock] 已收到问题：“{head}”。当前为离线回退；配置真实 LLM（.env 里 AI_PROVIDER 与 LLM_*）后此处返回生成式回答。"


_cached: ChatLLM | None = None


def get_llm() -> ChatLLM:
    global _cached
    if _cached is None:
        s = get_settings()
        if s.use_mock:
            log.info("LLM 使用 mock 回退（AI_PROVIDER=mock）")
            _cached = MockLLM()
        else:
            _cached = OpenAICompatLLM(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_temperature)
    return _cached

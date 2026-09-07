"""文生图：通义万相 / Z-Image（DashScope）+ mock 回退。

- mock 回退 = 纯标准库生成占位 PNG（颜色由 prompt 哈希决定，并把 prompt 写入 PNG 元数据），
  离线也能演示素材生产链路；接真实模型切 dashscope。
- dashscope 真实 = 调用百炼 multimodal-generation 端点（z-image-turbo 等），
  响应里的图片 URL 有效期仅 24 小时，须立即下载成字节返回（由上层存 MinIO）。
"""
from __future__ import annotations

import hashlib
import struct
import zlib

import httpx

from ..config import get_settings
from ..logging import get_logger
from .base import ImageGen, post_with_retry

log = get_logger("shopmind.ai.image")

# DashScope 文生图端点（z-image / wanx 通用，区别于老的 text2image/image-synthesis）
_IMAGE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def _solid_png(width: int, height: int, rgb: tuple[int, int, int], text: str) -> bytes:
    """纯标准库生成一张带 tEXt 元数据的纯色 PNG。"""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit RGB
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    idat = zlib.compress(raw, 9)
    text_chunk = b"prompt\x00" + text.encode("utf-8")
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"tEXt", text_chunk) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


class MockImageGen:
    def generate(self, prompt: str, **kwargs) -> bytes:
        h = int(hashlib.md5(prompt.encode("utf-8")).hexdigest(), 16)
        rgb = (h % 256, (h >> 8) % 256, (h >> 16) % 256)
        return _solid_png(kwargs.get("width", 512), kwargs.get("height", 512), rgb, prompt)


class DashScopeImageGen:
    """百炼文生图（z-image-turbo / wanx）：同步提交 → 取图片 URL → 下载字节。"""

    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def generate(self, prompt: str, **kwargs) -> bytes:
        size = kwargs.get("size", "1024*1024")
        body = {
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]}
                ]
            },
            "parameters": {"size": size},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = post_with_retry(_IMAGE_URL, json=body, headers=headers, timeout=120)
        data = resp.json()

        # 错误：非 2xx 由 post_with_retry raise；这里处理 2xx 但业务失败的情况
        if data.get("code"):
            raise RuntimeError(f"文生图失败：{data.get('code')} {data.get('message')}")

        choices = (data.get("output") or {}).get("choices") or []
        if not choices:
            raise RuntimeError(f"文生图响应无 choices：{str(data)[:200]}")
        content = (choices[0].get("message") or {}).get("content") or []
        image_url = None
        for c in content:
            if c.get("image"):
                image_url = c["image"]
                break
        if not image_url:
            raise RuntimeError(f"文生图响应无图片 URL：{str(data)[:200]}")

        # 图片 URL 24h 有效，立即下载
        img = httpx.get(image_url, timeout=120)
        img.raise_for_status()
        return img.content


_cached: ImageGen | None = None


def get_image_gen() -> ImageGen:
    global _cached
    if _cached is None:
        s = get_settings()
        if s.image_provider.strip().lower() == "mock":
            _cached = MockImageGen()
        else:
            _cached = DashScopeImageGen(s.dashscope_api_key, s.image_model)
    return _cached

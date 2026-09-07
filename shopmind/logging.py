"""统一日志：rich 控制台输出（方便演示），可切纯文本。"""
from __future__ import annotations

import logging
import sys

from .config import get_settings


def _force_utf8_stdout() -> None:
    """Windows 旧控制台默认 GBK 时强制 UTF-8 输出，避免中文/特殊符号乱码或 UnicodeEncodeError。"""
    try:
        import sys

        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def setup_logging(level: str | None = None) -> logging.Logger:
    _force_utf8_stdout()
    level = level or get_settings().log_level
    root = logging.getLogger("shopmind")
    if not root.handlers:
        try:
            from rich.logging import RichHandler

            handler: logging.Handler = RichHandler(rich_tracebacks=True, show_time=False)
        except Exception:  # rich 不可用时回退
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False
    return root


def get_logger(name: str = "shopmind") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)

"""ShopMind 共享核心包。

主线：“数据 → 知识 → AI 应用”闭环。
本包提供 5 个项目共用的：配置、DB/ES/MinIO/Redis 客户端、数据血缘、AI Provider（云端 + mock 回退）。
"""

__version__ = "0.1.0"

from .config import Settings, get_settings

__all__ = ["Settings", "get_settings", "__version__"]

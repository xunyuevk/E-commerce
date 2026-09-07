"""统一配置：pydantic-settings 从 .env / 环境变量加载。

所有“关键配置项”集中在这里，方便讲解：
  - 中间件连接串
  - AI Provider 的 base_url / model / key / 维度
  - 全局 mock 开关（离线回退）
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """从 cwd 向上找 .env，保证在任意子目录运行也能读到根配置。"""
    p = Path.cwd()
    for cand in (p, *p.parents):
        f = cand / ".env"
        if f.exists():
            return str(f)
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 基础设施 ----------
    mysql_host: str = "localhost"
    mysql_port: int = 3307  # 本机原生 mysqld 占用 3306，Docker MySQL 映射到 3307
    mysql_user: str = "shop"
    mysql_password: str = "shop_pass"
    mysql_database: str = "shopmind"
    mysql_root_password: str = "root_pass"

    es_url: str = "http://localhost:9200"
    es_index_prefix: str = "shopmind"

    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:19000"  # 避开 Windows 保留端口区间，Docker 映射到 19000
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "shopmind"

    # ---------- AI Provider ----------
    # 主开关：mock | openai-compatible | hybrid
    #   mock = 全部离线回退；openai-compatible = 全部走真实端点；
    #   hybrid = 按各 *_provider 单独决定（适合"只有 embedding key，LLM/rerank 还没 key"）
    ai_provider: str = "mock"
    # 各模块独立开关（留空则跟随 ai_provider）。取值：mock | openai-compatible
    llm_provider: str = ""
    embedding_provider: str = ""
    rerank_provider: str = ""

    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3

    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024  # 必须与模型真实输出对齐（ES dense_vector dims 用它）

    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    asr_provider: str = "mock"  # mock | aliyun | tencent
    aliyun_asr_access_key_id: str = ""
    aliyun_asr_access_key_secret: str = ""
    aliyun_asr_app_key: str = ""
    tencent_asr_secret_id: str = ""
    tencent_asr_secret_key: str = ""

    image_provider: str = "mock"  # mock | dashscope
    dashscope_api_key: str = ""
    image_model: str = "wanx-v1"

    log_level: str = "INFO"

    # ---------- 派生属性 ----------
    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def kb_index(self) -> str:
        """P2 知识库索引名。"""
        return f"{self.es_index_prefix}-kb"

    @property
    def use_mock(self) -> bool:
        """主对话(LLM)是否 mock——给 LLM 判官/生成相关逻辑用。"""
        return self.is_mock("llm")

    def effective_provider(self, kind: str) -> str:
        """某模块生效的 provider：优先 *_provider，其次跟随 ai_provider，默认 mock。"""
        specific = getattr(self, f"{kind}_provider", "") or ""
        if specific:
            return specific
        if self.ai_provider.strip().lower() == "openai-compatible":
            return "openai-compatible"
        return "mock"

    def is_mock(self, kind: str = "llm") -> bool:
        """某模块是否处于 mock 离线回退。"""
        return self.effective_provider(kind) == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()

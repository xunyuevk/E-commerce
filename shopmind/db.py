"""MySQL 数据层：SQLAlchemy engine + 参数化 SQL 助手。

选型说明（面试可讲）：
  - 用 SQLAlchemy Core engine 执行参数化 SQL，而非重量级 ORM：清洗/脱敏/血缘是批量操作，
    直接 SQL 性能可控、逻辑透明；
  - driver 选 pymysql（纯 Python，无需编译，Windows 下最稳），生产可换 asyncmy/aiomysql。
"""
from __future__ import annotations

import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings
from .logging import get_logger

log = get_logger("shopmind.db")

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_engine(
            s.mysql_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            future=True,
            echo=False,
        )
    return _engine


def execute(sql: str, params: dict | None = None) -> int:
    """执行写语句（自动提交），返回影响行数。"""
    with get_engine().begin() as conn:
        res = conn.execute(text(sql), params or {})
        return res.rowcount or 0


def fetchall(sql: str, params: dict | None = None) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
        return [dict(r) for r in rows]


def fetchone(sql: str, params: dict | None = None) -> dict | None:
    with get_engine().connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row is not None else None


def insert_get_id(sql: str, params: dict | None = None) -> int:
    """插入并返回自增主键（同连接取 LAST_INSERT_ID，避免跨连接取不到）。"""
    with get_engine().begin() as conn:
        conn.execute(text(sql), params or {})
        return int(conn.execute(text("SELECT LAST_INSERT_ID() AS id")).scalar_one())


def executemany(sql: str, rows: list[dict]) -> int:
    """批量插入，返回总影响行数。"""
    with get_engine().begin() as conn:
        res = conn.execute(text(sql), rows)
        return res.rowcount or 0


def wait_for_mysql(timeout: float = 120, interval: float = 2) -> None:
    """轮询等待 MySQL 就绪。"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            execute("SELECT 1")
            log.info("MySQL 就绪")
            return
        except Exception as e:  # noqa: BLE001
            log.debug("等待 MySQL：%s", e)
            time.sleep(interval)
    raise TimeoutError(f"MySQL 在 {timeout}s 内未就绪")


def init_schema(schema_path: str | Path | None = None) -> None:
    """按需建表（docker-entrypoint 已自动执行，这里用于非容器 MySQL 场景）。"""
    path = Path(schema_path or Path(__file__).resolve().parent.parent / "infra" / "mysql" / "init" / "001_schema.sql")
    raw = path.read_text(encoding="utf-8")
    # 去掉注释行后按分号切分，逐条执行
    statements = [
        s.strip()
        for s in raw.split(";")
        if s.strip() and not s.strip().startswith("--")
    ]
    with get_engine().begin() as conn:
        for stmt in statements:
            if stmt:
                conn.execute(text(stmt))
    log.info("schema 初始化完成：%s", path)

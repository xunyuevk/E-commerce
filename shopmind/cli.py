"""ShopMind 统一 CLI：聚合 5 个项目 + 基础设施自检。"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from shopmind import __version__
from shopmind.logging import setup_logging

app = typer.Typer(
    help="ShopMind：数据 → 知识 → AI 应用（电商客服 AI 体系化主线）",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# 聚合 5 个项目的子命令（p1..p5）
from p1_data_platform.cli import app as p1_app  # noqa: E402
from p2_customer_service_rag.cli import app as p2_app  # noqa: E402
from p3_live_insight.cli import app as p3_app  # noqa: E402
from p4_material_agent.cli import app as p4_app  # noqa: E402
from p5_lora_finetune.cli import app as p5_app  # noqa: E402

app.add_typer(p1_app, name="p1", help="统一数据资产平台（供血）")
app.add_typer(p2_app, name="p2", help="智能客服 RAG（数据→知识）")
app.add_typer(p3_app, name="p3", help="直播切片洞察引擎")
app.add_typer(p4_app, name="p4", help="素材生产 Agent")
app.add_typer(p5_app, name="p5", help="客服拟人化 LoRA 微调")


@app.command()
def version() -> None:
    """打印版本。"""
    console.print(f"ShopMind v{__version__}")


@app.command()
def doctor() -> None:
    """基础设施自检：MySQL / ES / Redis / MinIO 连通性。"""
    setup_logging()
    table = Table(title="基础设施自检")
    table.add_column("组件", style="cyan")
    table.add_column("状态")

    from shopmind import db
    from shopmind import es as es_client
    from shopmind.cache import get_redis
    from shopmind.storage import get_minio
    from shopmind.config import get_settings

    s = get_settings()

    def check(name: str, fn) -> None:
        try:
            fn()
            table.add_row(name, "[green]OK[/green]")
        except Exception as e:  # noqa: BLE001
            table.add_row(name, f"[red]FAIL[/red] {type(e).__name__}")

    check("MySQL", lambda: db.execute("SELECT 1"))
    check("Elasticsearch", lambda: es_client.get_es().ping())
    check("Redis", lambda: get_redis().ping())
    check("MinIO", lambda: get_minio().bucket_exists(s.minio_bucket))
    console.print(table)

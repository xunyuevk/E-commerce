"""P1 命令行入口（也作为 shopmind 主 CLI 的 p1 子命令）。"""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from shopmind import db
from shopmind.logging import setup_logging

from .pipeline import run_pipeline

app = typer.Typer(help="P1 统一数据资产平台（数据底座）")
console = Console()


@app.command("run")
def run() -> None:
    """执行完整流水线：采集 → 清洗 → 脱敏 → 资产化。"""
    setup_logging()
    summary = run_pipeline()
    console.print("\n[bold green]P1 流水线执行完成[/bold green]")
    table = Table(title="发布到业务表的数据量")
    table.add_column("资产", style="cyan")
    table.add_column("行数", justify="right")
    for k, v in summary["published_rows"].items():
        table.add_row(k, str(v))
    console.print(table)
    console.print(f"数据源 {summary['sources']} 个 | 资产 {summary['assets']} 个 | 血缘边 {summary['lineage_edges']} 条")


@app.command("assets")
def assets() -> None:
    """查看数据资产目录。"""
    setup_logging()
    rows = db.fetchall(
        "SELECT name, asset_type, location, owner, sensitivity, row_count FROM data_asset ORDER BY name"
    )
    table = Table(title="数据资产目录")
    for col in ("资产", "类型", "定位", "负责人", "敏感级", "行数"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["name"], r["asset_type"], r["location"], r["owner"] or "-", r["sensitivity"], str(r["row_count"]))
    console.print(table)


@app.command("lineage")
def lineage() -> None:
    """查看数据血缘图（源 → 关系 → 目标）。"""
    setup_logging()
    rows = db.fetchall(
        "SELECT s.name AS src, l.relation, d.name AS dst, l.description "
        "FROM lineage_edge l JOIN data_asset s ON s.id=l.src_asset_id "
        "JOIN data_asset d ON d.id=l.dst_asset_id ORDER BY l.id"
    )
    table = Table(title="数据血缘")
    for col in ("源", "关系", "目标", "说明"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["src"], r["relation"], r["dst"], r["description"] or "")
    console.print(table)


@app.command("desens-demo")
def desens_demo() -> None:
    """演示脱敏函数效果（不写库）。"""
    from . import desensitize

    sample = {"name": "张伟", "phone": "13812340001", "email": "zhangwei@example.com", "idcard": "110101199001011234"}
    console.print(json.dumps({
        "name": desensitize.mask_name(sample["name"]),
        "phone": desensitize.mask_phone(sample["phone"]),
        "email": desensitize.mask_email(sample["email"]),
        "idcard": desensitize.mask_idcard(sample["idcard"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()

"""P3 命令行入口（作为 shopmind 主 CLI 的 p3 子命令）。"""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shopmind import db
from shopmind.logging import setup_logging

from .pipeline import run_pipeline

app = typer.Typer(help="P3 直播切片洞察引擎")
console = Console()


def _load_products() -> dict[int, str]:
    """加载商品 id → 名称映射，用于把 product_ids 反解成可读名称。"""
    rows = db.fetchall("SELECT id, name FROM product")
    return {int(r["id"]): r["name"] for r in rows}


def _product_names(raw, products: dict[int, str]) -> str:
    """把 product_ids（JSON 字符串或 list）转成中文商品名，用顿号连接。"""
    if not raw:
        return "-"
    if isinstance(raw, str):
        try:
            ids = json.loads(raw)
        except ValueError:
            return "-"
    else:
        ids = raw
    names = [products.get(int(i), f"#{i}") for i in ids]
    return "、".join(names) if names else "-"


@app.command("run")
def run(
    video: str = typer.Option(None, "--video", help="本地视频文件路径，提供时按转写时间戳切出视频片段存 MinIO"),
    plan: str = typer.Option(None, "--plan", help="用户切分需求，提供时用 LLM 规划切分（需真实 ASR）"),
    segments: int = typer.Option(None, "--segments", help="LLM 规划切分的段数（默认自动 4~5 大段）"),
) -> None:
    """执行完整流水线：ASR → 分段 → 摘要/情感/关联 → 回血知识库。"""
    setup_logging()
    summary = run_pipeline(video_path=video, plan=plan, seg_count=segments)
    products = _load_products()
    rows = db.fetchall(
        "SELECT seq, topic, sentiment, product_ids FROM live_segment "
        "WHERE session_id=(SELECT id FROM live_session WHERE session_no=:no) ORDER BY seq",
        {"no": summary["session_no"]},
    )
    table = Table(title=f"直播切片（{summary['session_no']}，共 {summary['segments']} 段）")
    for col in ("seq", "topic", "sentiment", "product"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["seq"]),
            r["topic"] or "-",
            r["sentiment"] or "-",
            _product_names(r["product_ids"], products),
        )
    console.print(table)
    if summary.get("video_clips") is not None:
        console.print(f"[green]视频切片：{summary['video_clips']} 段已存 MinIO[/green]")


@app.command("list")
def list_segments(limit: int = typer.Option(50, "--limit", "-n", help="最多显示条数")):
    """列出历史切片（seq/topic/summary/product 名）。"""
    setup_logging()
    products = _load_products()
    rows = db.fetchall(
        "SELECT lv.session_no, r.anchor, ls.seq, ls.topic, ls.summary, ls.product_ids "
        "FROM live_segment ls "
        "JOIN live_session lv ON lv.id=ls.session_id "
        "JOIN live_room r ON r.id=lv.room_id "
        f"ORDER BY lv.created_at DESC, ls.seq ASC LIMIT {int(limit)}"
    )
    table = Table(title="历史直播切片")
    for col in ("场次", "主播", "seq", "topic", "摘要", "关联商品"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["session_no"],
            r["anchor"] or "-",
            str(r["seq"]),
            r["topic"] or "-",
            (r["summary"] or "")[:40],
            _product_names(r["product_ids"], products),
        )
    console.print(table)


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8001):
    """启动 HTTP 服务（切片浏览页 http://127.0.0.1:8001/）。"""
    import uvicorn

    from .serve import app as serve_app

    setup_logging()
    console.print(f"[green]启动服务：http://{host}:{port}  （/ 切片浏览页，/sessions /segments /clip）[/green]")
    uvicorn.run(serve_app, host=host, port=port, log_level="info")


@app.command("export")
def export() -> None:
    """为每段生成一条「多模态引用」摘要（标题 + 标签 + 商品 + 文案），打印即可。"""
    setup_logging()
    products = _load_products()
    rows = db.fetchall(
        "SELECT ls.seq, ls.topic, ls.summary, ls.sentiment, ls.product_ids "
        "FROM live_segment ls "
        "JOIN live_session lv ON lv.id=ls.session_id "
        "WHERE lv.id=(SELECT id FROM live_session ORDER BY created_at DESC LIMIT 1) "
        "ORDER BY ls.seq"
    )
    if not rows:
        console.print("[yellow]暂无切片，请先运行 p3 run。[/yellow]")
        return
    for r in rows:
        product = _product_names(r["product_ids"], products)
        tags = "、".join(t for t in (r["topic"], r["sentiment"], "直播切片") if t)
        copy = f"{(r['summary'] or '').rstrip('。')}——直播间专属价，点击购物车下单。"
        console.print(
            Panel(
                copy,
                title=f"标题：{r['topic']}",
                subtitle=f"标签：{tags}｜商品：{product}",
            )
        )


if __name__ == "__main__":
    app()

"""P4 命令行入口（作为 shopmind 主 CLI 的 p4 子命令）。"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shopmind import db
from shopmind.logging import setup_logging

from . import hitl
from .pipeline import advance, create_task
from .state_machine import ALLOWED_EVENTS, STATES, TRANSITIONS, is_terminal

app = typer.Typer(help="P4 素材生产 Agent")
console = Console()

_STATE_STYLE = {
    "human_review": "yellow",
    "approved": "green",
    "published": "green",
    "rejected": "red",
    "failed": "red",
}


@app.command("new")
def new(
    task_type: str = typer.Option(..., "--type", help="素材类型 product_copy|live_highlight|faq_expansion"),
    product_id: int = typer.Option(None, "--product-id", help="product_copy 必填"),
    segment_id: int = typer.Option(None, "--segment-id", help="live_highlight 必填"),
    topic: str = typer.Option(None, "--topic", help="faq_expansion 必填"),
) -> None:
    """创建素材任务并推进到 generating。"""
    setup_logging()
    payload: dict = {}
    if task_type == "product_copy":
        if product_id is None:
            raise typer.BadParameter("product_copy 需要 --product-id")
        payload = {"product_id": product_id}
    elif task_type == "live_highlight":
        if segment_id is None:
            raise typer.BadParameter("live_highlight 需要 --segment-id")
        payload = {"segment_id": segment_id}
    elif task_type == "faq_expansion":
        if topic is None:
            raise typer.BadParameter("faq_expansion 需要 --topic")
        payload = {"topic": topic}
    else:
        raise typer.BadParameter(f"未知类型 {task_type!r}，可选 product_copy|live_highlight|faq_expansion")

    task_no = create_task(task_type, payload)
    console.print(f"[green]已创建任务：[/green]{task_no}")


@app.command("run")
def run(task_no: str) -> None:
    """循环 advance 直到 human_review 或终态。"""
    setup_logging()
    row = db.fetchone(
        "SELECT id, task_type, state FROM material_task WHERE task_no=:n", {"n": task_no}
    )
    if row is None:
        console.print(f"[red]任务不存在：{task_no}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]推进任务 {task_no}（{row['task_type']}）[/bold]")
    while True:
        result = advance(row["id"])
        _print_advance(result)
        if result["state"] == "human_review" or is_terminal(result["state"]):
            break


@app.command("review")
def review(
    task_no: str,
    reviewer: str,
    decision: str,
    feedback: str = typer.Option(None, "--feedback", help="审核意见"),
) -> None:
    """人工审核（HITL）：decision 取 approve|reject。"""
    setup_logging()
    result = hitl.review(task_no, reviewer, decision, feedback)
    console.print(f"[green]审核完成：[/green]{task_no} → {result['state']}")


@app.command("publish")
def publish(task_no: str) -> None:
    """发布已审核通过的素材（文本落库 / FAQ 回血 / 可选配图）。"""
    setup_logging()
    result = hitl.publish(task_no)
    console.print(f"[green]发布完成：[/green]{task_no} → {result['state']}")
    for item in result["outputs"]:
        console.print(f"  - {item}")


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8002):
    """启动 HTTP 服务（素材生产页 http://127.0.0.1:8002/）。"""
    import uvicorn

    from .serve import app as serve_app

    setup_logging()
    console.print(f"[green]启动服务：http://{host}:{port}  （/ 素材生产页）[/green]")
    uvicorn.run(serve_app, host=host, port=port, log_level="info")


@app.command("status")
def status(task_no: str) -> None:
    """查看任务状态机当前状态、审核历史与产出。"""
    setup_logging()
    task = db.fetchone("SELECT * FROM material_task WHERE task_no=:n", {"n": task_no})
    if task is None:
        console.print(f"[red]任务不存在：{task_no}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"state=[bold]{task['state']}[/bold]  step={task['current_step']}  "
        f"compliance={task['compliance'] or '-'}  assignee={task['assignee'] or '-'}",
        title=f"任务 {task_no}（{task['task_type']}）",
    ))

    reviews = db.fetchall(
        "SELECT reviewer, decision, feedback, created_at FROM material_review WHERE task_id=:t ORDER BY id",
        {"t": task["id"]},
    )
    if reviews:
        table = Table(title="审核历史")
        for col in ("审核人", "结论", "意见", "时间"):
            table.add_column(col)
        for r in reviews:
            table.add_row(r["reviewer"], r["decision"], r["feedback"] or "-", str(r["created_at"]))
        console.print(table)

    outputs = db.fetchall(
        "SELECT content_type, object_key, status, created_at FROM material_output WHERE task_id=:t ORDER BY id",
        {"t": task["id"]},
    )
    if outputs:
        table = Table(title="产出")
        for col in ("类型", "对象 key", "状态", "时间"):
            table.add_column(col)
        for o in outputs:
            table.add_row(o["content_type"], o["object_key"] or "-", o["status"], str(o["created_at"]))
        console.print(table)


@app.command("transitions")
def transitions() -> None:
    """打印状态机全部迁移与各状态允许事件，演示可解释性。"""
    setup_logging()
    table = Table(title="P4 状态机迁移表（自写显式 TRANSITIONS）")
    for col in ("当前状态", "事件", "下一状态", "是否终态"):
        table.add_column(col)
    for (state, event), nxt in TRANSITIONS.items():
        table.add_row(state, event, nxt, "Y" if is_terminal(nxt) else "")
    console.print(table)

    table2 = Table(title="各状态允许的事件（ALLOWED_EVENTS）")
    table2.add_column("状态")
    table2.add_column("允许事件")
    for state in STATES:
        table2.add_row(state, ", ".join(ALLOWED_EVENTS(state)) or "（终态，无）")
    console.print(table2)


def _print_advance(result: dict) -> None:
    state = result["state"]
    style = _STATE_STYLE.get(state, "cyan")
    message = result.get("message") or result.get("action") or ""
    console.print(f"  [{style}]状态={state}[/{style}] {message}")
    if result.get("compliance"):
        console.print(f"  [dim]合规={result['compliance']} 命中词={result.get('hits') or []}[/dim]")
    if result.get("assignee"):
        console.print(f"  [dim]指派={result['assignee']}[/dim]")


if __name__ == "__main__":
    app()

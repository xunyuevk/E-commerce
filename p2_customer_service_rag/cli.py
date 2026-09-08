"""P2 命令行入口（作为 shopmind 主 CLI 的 p2 子命令）。"""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shopmind.logging import setup_logging

from .eval import run_all as run_eval
from .ingest import ingest_knowledge
from .pipeline import answer

app = typer.Typer(help="P2 智能客服 RAG（数据 → 知识）")
console = Console()


@app.command("ingest")
def ingest() -> None:
    """知识入库：文档/FAQ → 切片 → 向量 → ES。"""
    setup_logging()
    result = ingest_knowledge()
    console.print(f"[green]完成：文档 {result['documents']} 篇，切片 {result['chunks']} 条，索引 {result['index']}[/green]")


@app.command("ask")
def ask(question: str, no_cache: bool = typer.Option(False, "--no-cache", help="禁用语义缓存")):
    """单轮问答。"""
    setup_logging()
    r = answer(question, use_cache=not no_cache)
    tag = "[yellow](mock/离线)" if "mock" in r["answer"] else ""
    console.print(Panel(r["answer"], title=f"回答 {tag}", border_style="green" if r["answerable"] else "red"))
    meta = {
        "answerable": r["answerable"],
        "confidence": r["confidence"],
        "from_cache": r["from_cache"],
        "latency_ms": r["latency_ms"],
        "sources": [s["title"] for s in r["sources"]],
    }
    console.print(json.dumps(meta, ensure_ascii=False, indent=2))


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8000):
    """启动 HTTP 服务。"""
    import uvicorn

    from .serve import app as serve_app

    setup_logging()
    console.print(f"[green]启动服务：http://{host}:{port}  （/docs 交互文档，/chat 问答）[/green]")
    uvicorn.run(serve_app, host=host, port=port, log_level="info")


@app.command("eval")
def evaluate(rag: bool = typer.Option(False, "--rag", help="额外跑 LLM 判官的生成质量（较慢）")):
    """评测：默认 检索 + 拒答（纯检索、快）；--rag 加生成质量。"""
    setup_logging()
    metrics = run_eval(do_rag=rag)
    table = Table(title=f"评测结果（provider={metrics['provider']}, model={metrics['model']}）")
    table.add_column("指标", style="cyan")
    table.add_column("值")
    for group, sub in metrics.items():
        if not isinstance(sub, dict):
            continue
        for k, v in sub.items():
            table.add_row(f"{group}.{k}", str(v))
    console.print(table)
    if not rag:
        console.print("[dim]默认只跑检索/拒答（纯检索，无需 LLM 生成）。加 --rag 跑生成质量（LLM 判官，较慢）。[/dim]")


@app.command("demo")
def demo() -> None:
    """演示：域内问答 + 语义缓存命中 + 域外拒答。"""
    setup_logging()
    console.print("[bold]1) 域内问答（应可答）[/bold]")
    for q in ["支持7天无理由退货吗", "退款多久到账"]:
        console.print(f"\n用户：{q}")
        console.print(f"客服：{answer(q)['answer']}")
    console.print("\n[bold]2) 同义改写 → 语义缓存命中[/bold]")
    console.print("用户：退款几天能到账")
    r = answer("退款几天能到账")
    console.print(f"客服：{r['answer']}")
    console.print(f"  from_cache={r['from_cache']} matched_query={r.get('matched_query')}")
    console.print("\n[bold]3) 域外问题（应拒答）[/bold]")
    console.print("用户：今天天气怎么样")
    r = answer("今天天气怎么样")
    console.print(f"客服：{r['answer']}  (answerable={r['answerable']})")


if __name__ == "__main__":
    app()

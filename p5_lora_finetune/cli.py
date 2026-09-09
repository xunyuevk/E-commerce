"""P5 命令行入口（作为 shopmind 主 CLI 的 p5 子命令）。"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from shopmind.logging import setup_logging

from . import eval_sets
from .build_dataset import build_sft_dataset
from .eval_before_after import run_compare

app = typer.Typer(help="P5 客服拟人化 LoRA 微调")
console = Console()


@app.command("build-dataset")
def build_dataset() -> None:
    """从真实客服会话抽取 SFT 语料（conversation → data/sft_train.jsonl）。"""
    setup_logging()
    stats = build_sft_dataset()
    table = Table(title="SFT 数据集构建结果")
    table.add_column("指标", style="cyan")
    table.add_column("值", justify="right")
    for k, v in stats.items():
        table.add_row(k, str(v))
    console.print(table)


@app.command("eval-datasets")
def eval_datasets() -> None:
    """落库双评测集：拟人化 + 客服规范。"""
    setup_logging()
    ids = eval_sets.build_datasets()
    table = Table(title="P5 双评测集")
    table.add_column("评测集", style="cyan")
    table.add_column("dataset_id", justify="right")
    table.add_column("样本数", justify="right")
    for name, did in ids.items():
        n = len(eval_sets.HUMANIZE_SET if name == "humanize" else eval_sets.COMPLIANCE_SET)
        table.add_row(name, str(did), str(n))
    console.print(table)


@app.command("compare")
def compare() -> None:
    """跑 before/after 双端点评测并对比（base vs finetuned）。"""
    setup_logging()
    result = run_compare()
    before, after = result["before"], result["after"]
    table = Table(title="before/after 对比")
    table.add_column("指标", style="cyan")
    table.add_column("before(base)", justify="right")
    table.add_column("after(finetuned)", justify="right")
    table.add_row("humanize_avg", str(before["humanize_avg"]), str(after["humanize_avg"]))
    table.add_row("compliance_avg", str(before["compliance_avg"]), str(after["compliance_avg"]))
    table.add_row("fallback", str(before["fallback"]), str(after["fallback"]))
    table.add_row("model", str(before["model"]), str(after["model"]))
    console.print(table)
    if after.get("fallback") or before.get("fallback"):
        console.print("[yellow]fallback=True：未配置 LLM_FINETUNED_*，finetuned 端点回退到 base，二者一致属预期。[/yellow]")
    console.print("[dim]mock 模式数字只验证链路；真实对比请配置两个真实端点后重跑。[/dim]")


@app.command("finetune")
def finetune() -> None:
    """可选：本地 LoRA 微调（需 torch/transformers/peft/datasets）。"""
    setup_logging()
    try:
        from .finetune import main as finetune_main

        result = finetune_main()
        console.print(f"[green]微调完成：{result['model_name']} → {result['output_dir']}[/green]")
    except ImportError as e:
        console.print(f"[yellow]未安装微调依赖（{getattr(e, 'name', e)}），跳过本地 LoRA 训练。[/yellow]")
        console.print("[dim]替代：用云微调 API 上传 data/sft_train.jsonl，把端点填到 LLM_FINETUNED_* 后跑 `compare`。[/dim]")


if __name__ == "__main__":
    app()

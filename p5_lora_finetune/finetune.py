"""P5 微调（可选路径）：LoRA SFT 一个小模型。

本地路径：一张 4060（8GB）可跑 Qwen/Qwen2.5-3B-Instruct 的 LoRA 微调（r=8）。
torch / transformers / peft / datasets 体积大，**只在 main() 函数体内惰性 import**，
保证未装 torch 时 cli import 不崩（`shopmind p5 finetune` 会友好提示并跳过）。

云微调 API 替代（等价路径）：若不想本地跑，可把 data/sft_train.jsonl 上传到
ModelScope / 硅基流动 / 魔搭社区等平台的 SFT 任务，拿到返回的模型服务端点后填到
LLM_FINETUNED_BASE_URL / LLM_FINETUNED_API_KEY / LLM_FINETUNED_MODEL，再跑
`shopmind p5 compare` 即可——评测链路与本地微调完全相同。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from .build_dataset import DATA_DIR

DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"
CONFIG_PATH = Path(__file__).resolve().parent / "configs" / "lora.yaml"
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def load_config() -> dict:
    """读取 configs/lora.yaml，返回训练配置 dict。"""
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> dict:
    """执行 LoRA SFT（惰性 import torch/transformers/peft/datasets）。

    训练样本从 data/sft_train.jsonl 读取，LoRA 参数与超参来自 configs/lora.yaml。
    """
    import torch  # noqa: F401  # 惰性 import：未装 torch 时由 cli 捕获 ImportError
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    cfg = load_config()
    model_name = os.getenv("SFT_BASE_MODEL", cfg.get("model_name", DEFAULT_MODEL))
    jsonl = DATA_DIR / "sft_train.jsonl"
    if not jsonl.exists():
        raise FileNotFoundError(f"缺少 SFT 语料 {jsonl}，请先跑 `shopmind p5 build-dataset`")

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 读取 OpenAI Chat 格式 JSONL，转为可训练的文本序列
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    texts: list[str] = []
    for r in rows:
        msgs = r["messages"]
        try:
            texts.append(tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False))
        except Exception:  # noqa: BLE001  # 无 chat template 时兜底手动拼接
            texts.append("\n".join(f"{m['role']}: {m['content']}" for m in msgs))

    def tokenize_fn(examples: dict) -> dict:
        return tokenizer(
            examples["text"],
            truncation=True,
            max_length=int(cfg.get("max_seq_len", 1024)),
            padding=False,
        )

    ds = Dataset.from_dict({"text": texts}).map(tokenize_fn, batched=True, remove_columns=["text"])

    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=int(cfg.get("r", 8)),
        lora_alpha=int(cfg.get("lora_alpha", 16)),
        target_modules=list(cfg.get("target_modules", ["q_proj", "k_proj", "v_proj", "o_proj"])),
        lora_dropout=float(cfg.get("lora_dropout", 0.05)),
        bias="none",
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True,
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(OUTPUT_DIR),
        per_device_train_batch_size=int(cfg.get("batch_size", 1)),
        gradient_accumulation_steps=int(cfg.get("gradient_accumulation_steps", 8)),
        num_train_epochs=float(cfg.get("epochs", 3)),
        learning_rate=float(cfg.get("lr", 2e-4)),
        logging_steps=1,
        save_strategy="epoch",
        bf16=torch.cuda.is_available(),
        fp16=False,
        report_to=[],
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()
    adapter_dir = OUTPUT_DIR / "lora-adapter"
    trainer.save_model(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    return {"model_name": model_name, "output_dir": str(adapter_dir), "global_step": int(trainer.state.global_step)}

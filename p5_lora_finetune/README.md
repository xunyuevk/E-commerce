# P5 · 客服拟人化 LoRA 微调 + 双评测集（收官项目）

> 主线角色：**收官——把 P1 积累的真实会话数据变现**，完成「数据 → 知识 → AI 应用 → 新数据回血」闭环的最后一跳。

## 一句话

把 P1 高满意度客服会话抽成 **SFT 语料**，用 **LoRA 微调**小模型让客服回答更拟人，再用「**拟人化 + 规范**」双评测集做 **before/after 对比**，用数字证明微调收益。

## 架构链路

```
conversation / message（P1 供血）
   └─ build_sft_dataset：取 satisfaction>=4 会话，抽最后一轮 (customer→agent) 问答对
        └─ data/sft_train.jsonl（OpenAI Chat 格式：system/user/assistant）
             ├─ finetune.py：LoRA SFT 小模型（可选，惰性 import torch）→ outputs/lora-adapter
             │        └─ 部署为服务端点（本地 vLLM / 云微调 API）
             └─ 回血 MinIO finetune/sft_train.jsonl + 资产/血缘/审计
双评测集（eval_sets.py，落库 eval_dataset/eval_item）
   ├─ p5_humanize（10 条）：自然度 / 口语化 / 共情
   └─ p5_compliance（8 条）：准确性 / 守规 / 不夸大
   └─ eval_before_after.run_compare()：base vs finetuned 各打一遍
        └─ judge.py 打分（0~5）→ 写 eval_run（run_tag=before/after）
```

## 运行

前置：`docker compose up -d`、`cp .env.example .env`、先跑 P1 供血。

```bash
uv run shopmind p1 run                # P1 供血（若还没跑，conversation/message 数据来源）
uv run shopmind p5 build-dataset      # 抽 SFT 语料 → data/sft_train.jsonl + MinIO
uv run shopmind p5 eval-datasets      # 落库双评测集（humanize + compliance）
uv run shopmind p5 compare            # before/after 对比（base vs finetuned 打分）
uv run shopmind p5 finetune           # 可选：本地 LoRA 微调（未装 torch 会友好提示并跳过）
```

mock 模式（`AI_PROVIDER=mock`、无 torch）下 `build-dataset` / `eval-datasets` / `compare` 三条命令均可跑通：
`compare` 的两个端点都是 `MockLLM`、结果一致，只验证链路。

## 接真实模型做真实对比

1. 本地微调出适配器后，用 vLLM 等服务把它起成 OpenAI 兼容端点；或用**云微调 API** 上传 `data/sft_train.jsonl` 拿到服务端点；
2. 配置微调端点（环境变量）：

```bash
LLM_FINETUNED_BASE_URL=https://your-finetuned-endpoint/v1 \
LLM_FINETUNED_API_KEY=sk-xxx \
LLM_FINETUNED_MODEL=your-finetuned-model \
uv run shopmind p5 compare
```

`.env` 里 `AI_PROVIDER=openai-compatible` + `LLM_*` 作为 base 端点，微调端点走 `LLM_FINETUNED_*`，即可得到真实 before/after 数字。

## 关键选型（面试逐条可展开）

| 决策点 | 选择 | 为什么 / 备选 |
| :--- | :--- | :--- |
| LoRA vs 全参微调 | **LoRA**（r=8，q/k/v/o_proj） | 只训约 0.1%~1% 参数，4060(8GB) 可跑 3B；全参需更大显存/更多数据，收益边际递减；备选 QLoRA(4bit) 再省显存 |
| 3B 小模型 vs 大模型 API | **本地 3B（Qwen2.5-3B-Instruct）** | 拟人化是「风格」任务，小模型学得动、可私有化、成本可控；通用知识仍靠大模型 API 兜底 |
| 双评测集分「拟人化」「规范」 | **分两套、分开打分** | 「更像人」与「不出错」正交：拟人化过头会开始编造/夸大，规范过头又机械官腔；分开评才能同时守住两条线 |
| 云微调 API vs 本地 4060 | **本地 4060 主推，云 API 等价替代** | 本地数据不出域、可迭代；云端省机器、上手快，评测链路完全复用 |

## 面试高频追问自查

1. “SFT 样本怎么从会话里抽？”→ 只取高满意度（>=4）会话，抽最后一轮 customer→agent 问答对，user=用户上一句、assistant=客服回复，套统一人设 system 提示词。
2. “为什么按满意度过滤？”→ 高满意度会话 ≈ 客服回复质量高的正样本，低满意度/未解决会话可能带坏模型；可进一步用「是否 resolved + 满意度」双条件。
3. “LoRA 为什么只挂 q/k/v/o 四个 proj？”→ 注意力投影层是语义/风格迁移收益最高的位置，全挂 MLP 收益小还占显存；r=8、alpha=16 是 3B 量级常用经验值。
4. “怎么证明微调真有效？”→ 双评测集 before/after：base 打一遍、finetuned 打一遍，看 humanize_avg 上升且 compliance_avg 不掉（不因拟人化而变夸大/违规）。
5. “mock 下 compare 有意义吗？”→ 只有链路意义（保证无 Key 也能跑通）；真实对比必须配两个真实端点，否则 before/after 都是 MockLLM、数字一致。
6. “为什么判官用 LLM 打分？”→ 拟人化/规范没有精确 ground_truth，人工打分成本高；LLM 判官可扩展、可复跑，mock 下用启发式兜底，解析失败回退 2 分。

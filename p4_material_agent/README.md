# P4 · 素材生产 Agent（自写状态机 + HITL + 合规双通道）

> 主线角色：**证明能力可复制**——把 P1 的数据（商品/直播切片）变成可发布的营销素材，
> 并把 FAQ 回血中台，完成"数据 → 知识 → AI 应用 → 新数据回血"的闭环。

## 一句话

一个带**自写显式状态机 + 人工审核流（HITL）+ 合规双通道**的素材生产 Agent，
从商品/直播切片取数生成营销文案与 FAQ，经规则+LLM 双通道合规、人工审核后发布或回血。

## 状态机（自写，非 LangGraph）

```
                 start                      generated
  ┌─────────┐ ─────────────► ┌─────────────┐ ─────────────► ┌───────────────────┐
  │  draft  │                 │ generating  │                 │ compliance_check  │
  └─────────┘                 └─────────────┘                 └───────────────────┘
                                     │ error                         │  compliance_pass
                                     ▼                               │  compliance_review
                               ┌─────────┐                          ▼
                               │ failed  │                  ┌──────────────┐
                               └─────────┘                  │ human_review │
                                                            └──────────────┘
                                          approve ────────────────│──── reject
                                             │                    │
                                             ▼                    ▼
                                       ┌───────────┐       ┌───────────┐
                                       │ approved  │       │ rejected  │
                                       └───────────┘       └───────────┘
                                             │ publish
                                             ▼
                                       ┌────────────┐
                                       │ published  │
                                       └────────────┘
  （compliance_fail → rejected；generating / compliance_check / human_review / approved 的 error → failed）
```

终态：`approved / rejected / published / failed`。`approved` 虽可由 `publish` 继续推进，
但对"自动推进"而言已是稳定终点，需外部显式动作才离开。

## 数据流

```
product / live_segment（P1 供血）
        │  generate（agent，mock/真实）
        ▼
  result_json（结构化素材）
        │  combined_check（合规双通道：规则引擎 → LLM 复核）
        ▼
  human_review（HITL：停住，等人 approve/reject）
        │  approve → publish
        ▼
  material_output（text / image，image 存 MinIO）
        └─ faq_expansion：逐条 INSERT INTO faq + add_lineage("material_output"→"faq","feeds")
```

## 运行

前置：`docker compose up -d`（MySQL / MinIO）、`cp .env.example .env`、先跑 P1 供血。

```bash
# 1) 创建任务（推进到 generating）
uv run shopmind p4 new --type product_copy --product-id 1
uv run shopmind p4 new --type live_highlight --segment-id 1
uv run shopmind p4 new --type faq_expansion --topic "退换货政策"

# 2) 循环推进到 human_review（合规 pass 后停下等人工）
uv run shopmind p4 run MT-product_copy-20250101120000

# 3) 人工审核（HITL）
uv run shopmind p4 review MT-... 张三 approve --feedback "通过"
uv run shopmind p4 review MT-... 张三 reject --feedback "文案夸大"

# 4) 发布（文本落库 / FAQ 回血 / 可选配图）
uv run shopmind p4 publish MT-...

# 5) 查看状态 / 审核历史 / 产出；打印状态机全量迁移
uv run shopmind p4 status MT-...
uv run shopmind p4 transitions
```

mock 模式（默认 `AI_PROVIDER=mock`，无 API Key）可跑通：`new → run（停在 human_review）→ review approve → publish`。

## 关键选型

| 决策点 | 选择 | 为什么 / 备选 |
| :--- | :--- | :--- |
| 编排 | **自写显式状态机**（一张 `TRANSITIONS` dict） | 状态少且固定（8 状态 9 事件）、可审计可打断、零依赖；LangGraph 的图编译/checkpoint 对"审核流"过度设计，Celery 是任务队列不是状态机 |
| 状态迁移 | `(state, event) -> new_state` 显式枚举，非法迁移抛 `ValueError` | 迁移图可查（`transitions` 命令直接打印），杜绝"隐式跳转"与黑盒 |
| 合规 | **双通道：规则引擎 + LLM 复核** | 规则引擎确定性拦截字面词（零成本零延迟、可解释），LLM 拦语义夸大（规则漏网），任一 fail 则 fail |
| 规则引擎 | 子串匹配 `RULE_BANNED_WORDS` 命中即 fail | 广告法敏感词硬门禁，宁错杀不放过；生产可换正则/词典库 |
| HITL | human_review 阶段状态机**停住**，必须人 approve/reject | 发布即对外、责任在人；AI 生成可能被合规漏判，不能替人做最终决定 |
| 生成 | 三种 task_type 分派提示词，真实输出 JSON 再 parse，mock 结构化 + `[mock]` 标注 | mock 结果明确标注，避免与真实内容混淆；真实统一 JSON 便于落库与二次加工 |
| FAQ 回血 | 逐条 `INSERT INTO faq` + `add_lineage` 记血缘 | 把 P4 产出回流 P2 知识库，闭环落到可查询的血缘表 |

## 面试追问自查

1. "为什么自写状态机而不是 LangGraph？"→ 状态少且固定，一张 dict 全枚举；要可审计（每个迁移是显式键值对）、可打断（human_review 停住等外部事件）；LangGraph 引入图执行黑盒与额外依赖，当前收益为负。演进话术：出现并行/重试/子图再评估 LangGraph/Temporal。
2. "非法迁移怎么处理？"→ `transition()` 抛 `ValueError` 并说明该状态允许的事件列表；所有状态变更都先过 `transition` 再写库，保证状态机是唯一真相源。
3. "为什么合规要双通道？"→ 规则引擎只认字面词、拦不住语义夸大（"用了都说好"），LLM 拦语义但可能幻觉/不稳定，二者互补；规则确定性先行（零成本），LLM 兜底语义，任一 fail 则 fail。
4. "HITL 为什么必须有人？"→ 发布即对外、责任在人；合规引擎（规则+LLM）是"辅助判断"不是"替人担责"，human_review 状态机停住，人 approve 后才到 approved，再人 publish 才对外。
5. "review 和 reject 的区别？"→ review 是合规存疑转人工复核（assignee=合规复核员），reject 是明确违规直接拒绝；都落在状态机里，审计可查。
6. "mock 怎么保证能跑通且不骗人？"→ mock 结果统一 `[mock]` 前缀，链路照走、数字可复现；接真实模型只改 `.env` 的 `AI_PROVIDER`/`LLM_*`。

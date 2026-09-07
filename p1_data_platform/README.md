# P1 · 统一数据资产平台（数据底座）

> 主线角色：**心脏**，为 P2~P5 供血；也是整个体系“数据 → 知识 → AI 应用”闭环的起点。

## 它解决什么问题

5 个 AI 应用如果各自维护一份数据，会面临口径不一致、PII 泄露、无法溯源的问题。
本平台把“数据”统一管起来，提供四个能力：

1. **采集**：原始数据（含 PII）落地对象存储，登记数据源；
2. **清洗**：去空、去重、规范化、范围校验（规则登记在 `cleaning_rule` 表）；
3. **脱敏**：姓名/手机/邮箱/身份证掩码，业务表只存脱敏数据（规则在 `desensitization_rule` 表）；
4. **资产化**：表/文件登记为资产目录，连出血缘（`lineage_edge`），全程审计（`audit_log`）。

## 数据流

```
原始数据(含 PII) --采集--> MinIO raw/*.json
      --清洗--> 干净数据(仍含 PII)
      --脱敏--> 可发布数据(掩码后)
      --发布--> MySQL 业务表 + 知识文档进 MinIO
      --登记--> data_asset + lineage_edge + audit_log
```

## 运行

前置：`docker compose up -d` 起 MySQL/ES/Redis/MinIO，`cp .env.example .env`。

```bash
# 从仓库根目录
uv run shopmind p1 run          # 一键跑完整流水线
uv run shopmind p1 assets       # 查看资产目录
uv run shopmind p1 lineage      # 查看血缘图
uv run shopmind p1 desens-demo  # 单独演示脱敏效果
```

（不用 uv 也可：`python -m p1_data_platform.cli run`，但需先 `pip install -e .`）

## 关键配置 / 选型（面试可讲）

| 决策点 | 选择 | 为什么 |
| :--- | :--- | :--- |
| 脱敏时机 | 落业务表**前**脱敏，原始 PII 只存采集层 | 最小化 PII 暴露面；业务表可自由下发给分析/AI 任务 |
| 关联键 | 用 `cid`/`sku` 等业务键，不用手机号做关联 | PII 不做主键/外键，脱敏不影响关联 |
| 正文存储 | 知识文档正文进 MinIO，MySQL 只存 `object_key` | 大对象外置，MySQL 保持轻量 |
| 血缘模型 | `src → dst + relation(feeds/derives_from)` | 有向图即可表达“谁供血、谁派生”，够用不过度设计 |
| 清洗/脱敏 | 规则数据化（存表），执行在 Python | 规则可审计、可扩展，不写死 |

## 产出物（供后续项目消费）

- 业务表：`customer` `product` `orders` `order_item` `conversation` `message` `ticket` `faq`
- 知识文档：`knowledge_doc`（`status=staged`，正文在 MinIO `knowledge/*.md`）→ 等 P2 切片入库
- 资产目录 + 血缘图（P2~P5 每次取数/回血都会追加血缘边）

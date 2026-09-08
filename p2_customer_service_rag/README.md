# P2 · 智能客服 RAG（旗舰项目，40% 时间）

> 主线角色：**第一个 AI 应用**，把 P1 的数据底座变成可检索的“知识”，完成 **数据 → 知识** 的关键一跳。

## 一句话

一个带**混合检索 + 重排 + 拒答 + 语义缓存 + 评测闭环**的电商客服 RAG，从 P1 的知识文档/FAQ 取数，生成可上线的客服回答。

## 架构链路

```
用户问题
  ├─ ① 语义缓存（query embedding 相似度命中 → 直接返回，省钱省时）
  ├─ ② 混合检索（ES：BM25 走 content_tokens + kNN 走 dense_vector，RRF 融合）
  ├─ ③ 重排（bge-reranker，重排后取 top_k）
  ├─ ④ 拒答判断（重排最高分 < 阈值 → 拒答，转人工）
  └─ ⑤ 生成（RAG 提示词 → LLM）→ 写回语义缓存
```

## 运行

前置：`docker compose up -d`、`cp .env.example .env`、先跑 P1 供血。

```bash
uv run shopmind p1 run      # P1 供血（若还没跑）
uv run shopmind p2 ingest   # 知识入库（切片→向量→ES）
uv run shopmind p2 demo     # 端到端演示（域内/缓存/拒答）
uv run shopmind p2 ask "退款多久到账"
uv run shopmind p2 eval     # 三套评测
uv run shopmind p2 serve    # 起 HTTP 服务 http://127.0.0.1:8000/docs
```

## 关键设计（面试逐条可展开）

| 决策点 | 选择 | 为什么 / 备选 |
| :--- | :--- | :--- |
| 混合检索 | ES BM25 + kNN，**RRF 融合** | RRF 对两路分数量纲不敏感、免归一化；备选加权求和需调 α 且对 score 分布敏感 |
| 中文 BM25 | **jieba 预分词写 `content_tokens`，ES whitespace 分析器** | 免装 ik 插件、分词可控；生产可切 `ik_max_word`（只改 mapping + 重灌） |
| 切片 | 段落感知 + 重叠窗口；FAQ 单条成块 | 避免把语义单位切断；`chunk_size/overlap` 用检索命中率实验定 |
| 重排 | 先召回 top_k(10) 再重排取 top(5) | 两段式召回精度/成本平衡；`bge-reranker-v2-m3` 交叉编码精度高于双塔 |
| 拒答 | 重排最高分 < `REFUSAL_THRESHOLD` 拒答 | 用 refusal 评测集校准阈值，避免“幻觉式硬答” |
| 语义缓存 | query embedding 余弦相似度 ≥ `CACHE_THRESHOLD` 命中 | 同义改写也能命中；demo O(N) 扫描，生产 FAISS/向量库 |
| 评测 | 自研三套（hit@k/MRR、拒答准确率、LLM 判官）+ 可选接 RAGAS | 数字驱动调参：先基线 → 调阈值 → 复测 |

## 阈值调参（“真实运行数字”来源）

在 `.env` 可调，跑 `p2 eval` 对比：

```bash
TOP_K=10 RERANK_TOP=5 HYBRID_ALPHA=0.5 RRF_K=60 \
REFUSAL_THRESHOLD=0.05 CACHE_THRESHOLD=0.92 CACHE_TTL=3600
```

调参故事：先固定 embedding/rerank，扫 `REFUSAL_THRESHOLD`，观察“拒答准确率”与“域内漏答率”的权衡，选 F1 最高点。

## 接真实模型

`.env` 里改：`AI_PROVIDER=openai-compatible`，填 `EMBEDDING_*` / `RERANK_*` / `LLM_*` 的 base_url/api_key/model，重跑 `p2 ingest`（向量维度必须与 `EMBEDDING_DIM` 对齐）+ `p2 eval`。

## 面试高频追问自查

1. “为什么不是纯向量检索？”→ 精确词（SKU、政策条款名）BM25 更稳，语义改写向量更稳，二者互补。
2. “RRF 和加权求和区别？”→ RRF 只看排名不看分数绝对值，对量纲鲁棒，工业界（Weaviate）内置。
3. “拒答阈值怎么定？”→ 评测集扫参，看拒答准确率 vs 漏答率，取 F1 峰值。
4. “语义缓存会不会答错？”→ 只缓存“可答”的答案 + 相似度阈值兜底 + 可设 TTL，且缓存命中标记 `from_cache` 便于审计。

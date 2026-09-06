# 同语料检索实验：工具与首轮试跑

更新（2026-09-07）：历史图谱与 Milvus 已重建并切换至 1,019 个正式回合，语料和 AI 标签重新冻结，见 [v2 验收](HISTORICAL_DATA_REBUILD_V2.md)。下文原始数字和结果按其运行时版本保留；旧引用与旧实验必须配套旧数据库快照。

2026-09-06：实验工具已实现，独立相关性标签仍待审核。当前报告是工程试跑，Recall、nDCG、无答案误召回率和正例误拒答率均为 null。命令默认拒绝未审核标签；必须显式指定 `--allow-unreviewed` 才能输出无评分试跑。

## 实验边界

- 同一份 1,023 回合语料，覆盖原有 20 场比赛。检索文档是名单与可观察事件事实的统一文本，保留源回合和原始事件用于复核。
- 文本对照：SQLite FTS5 BM25、精确 dense 余弦检索、dense + BM25 RRF（常数 60）。全部使用同一 text、相同 top-k 和地图/比赛/回合前置过滤。
- 结构化参考：事件表 SQL 与“回合→事件”图路径；它们额外读取人工给定 event_kind，因此单列，不能与文本方法的分差解释为图算法优势。二者不是生产 GraphRAG 全部能力的替身。
- 每种方法分别开启/关闭名单实体过滤。实体条件含义是该选手/战队参赛，不代表其实施了所问事件。自动解析实体名称的能力不在本轮测量范围内。
- 不使用生产 Milvus 或远程 LLM。dense 在候选集非空时始终返回 top-k，没有从测试集拟合拒答阈值。

## 表示与性能口径

FastEmbed 0.8.0 下该 MiniLM 模型的实际 tokenizer 上限为 128。工具按 118 token 分块，验证每块编码不会截断，覆盖完整统一文本，再对块向量等权平均并归一化。1,023 回合共产生 4,389 块；模型文件 SHA-256、池化规则、环境版本和源码哈希写入报告。

BM25 使用 SQLite unicode61，未加入中文分词或查询翻译；查询集包含中英文各 8 条。后续应按语言分层报告，不能将语言处理差异直接归因于检索范式。

以下为 v2 试跑、实体约束开启时的本机耗时快照。每条查询首次执行另存，后续 3 次用于热态分位数；这不是进程冷启动测量。搜索计时包含公共过滤；RRF 包含两个分支搜索成本。查询编码单独列出，不能用 dense 的搜索耗时替代端到端耗时。

| 文本方法 | 热搜索 p50 / p95 (ms) | 查询编码 p50 (ms) |
| --- | ---: | ---: |
| BM25 | 0.99 / 3.51 | 0 |
| Dense | 0.27 / 0.43 | 257.79 |
| Dense + BM25 RRF | 1.01 / 3.55 | 257.79 |

| 结构化参考 | 热搜索 p50 / p95 (ms) |
| --- | ---: |
| SQL 事件过滤 | 0.26 / 0.45 |
| 回合→事件路径 | 0.64 / 1.27 |

所有方法合计 16 查询 × 5 方法 × 2 种过滤配置 = 160 条结果。开启实体条件后，非空结果的条件符合度为 1，是显式过滤的工程性质，不是相关性准确率；无结果的查询不进入该均值。`p`/`n` 查询 ID 只是制定时的命名，不代替审核后的正负标签。

## 复现

需要本地名单补齐后的图谱与已经缓存的模型文件。原始 Demo、数据库、统一语料与模型不进入 Git；从源码仓库单独 clone 后必须先取得对应数据。小型合成 fixture 可通过离线测试验证算法与校验逻辑。

```bash
# 每次使用新的输出路径；工具拒绝覆盖旧实验。
.venv/bin/python scripts/evaluate_fair_retrieval.py prepare \
  --output data/evaluation/fair_reproduction/corpus.jsonl

.venv/bin/python scripts/evaluate_fair_retrieval.py packet \
  --corpus data/evaluation/fair_reproduction/corpus.jsonl \
  --queries datasets/evaluation/fair_queries_v1.json \
  --output data/evaluation/fair_reproduction/qrels-review.json

make eval-fair ARGS="--corpus data/evaluation/fair_reproduction/corpus.jsonl --queries datasets/evaluation/fair_queries_v1.json --qrels data/evaluation/fair_reproduction/qrels-review.json --allow-unreviewed --output data/evaluation/fair_reproduction/smoke.json"

.venv/bin/python -m pytest -q test_fair_retrieval.py
```

正式评测移除 `--allow-unreviewed`，提供审核完成的标签副本。独立审核者应先读取冻结语料，不看召回排序；对每条查询完整检查允许的地图/比赛范围，记录所有相关回合、0–3 相关性等级和源事件依据。只有确实全范围无答案才保留空相关集合并标为已审核。工具验证来源、唯一性、完整性声明和哈希，但无法证明填写者确实独立审核；审核记录仍需人工负责。

## 产物与未完成项

- [冻结语料清单](../datasets/evaluation/fair_corpus_manifest_v1.json)、[16 条查询](../datasets/evaluation/fair_queries_v1.json)、[待审核标签包](../datasets/evaluation/fair_qrels_review_v1.json)。清单中的实现哈希对应第一次试跑；后续报告分别保存当次源码哈希。
- [v1 试跑](../datasets/evaluation/fair_retrieval_smoke_v1_report.json) 保留；[v2 试跑](../datasets/evaluation/fair_retrieval_smoke_v2_report.json) 增加严格命令入口后重跑，查询与语料未改。
- 待完成：独立标签审核、按语言与比赛分组的质量统计及区间、受控冷启动测量、更多未见比赛。不能从当前材料声称 GraphRAG 检索优于文本基线。

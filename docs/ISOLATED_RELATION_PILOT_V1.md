# 隔离比赛关系检索试点

两场已下载且已用于解析验收的系列：G2–NAVI（2396940，2 图）与 G2–Aurora（2396944，3 图），合计 111 个正式回合。它们与历史图谱按系列隔离，保存在单独 SQLite / 文本语料，未写入生产 GraphRAG 或 Milvus。这里是**已观察比赛上的检索开发试点**，不能重新标为未见比赛盲测。

准备逻辑与输入在 `c74be08` 冻结；语料、30 个语义问题 / 60 个中英文表述、标签和检索协议在 `8160af0` 冻结，然后首次跑分。每图覆盖首杀、下包后击杀和补枪，每类选 1 正例 / 1 负例，均要求范围内有相似干扰回合。按预先固定哈希选择选手对，不按检索表现选择；无缺失配额。

标签穷举 666 个问题–回合组合，Python 谓词与独立 SQL join 的结果及干扰事件一致。AI 辅助审核共享解析事实，不冒称独立人工金标准或原始 Demo 的独立测量。

## 首次结果

15 个正例语义组，中英文配对平均；15 个负例单列，k=5。文本方法使用同一事实语料、显式实体 / 范围与未修改的先前参数。

| 方法（原始问法） | nDCG@5 | Recall@5 | 无答案误召回 |
| --- | ---: | ---: | ---: |
| unicode61 BM25 | 0.1584 | 0.2222 | 100% |
| 子词 BM25 | 0.2036 | 0.3000 | 100% |
| MiniLM dense | 0.2028 | 0.2500 | 100% |
| Jina 中英 dense | 0.2213 | 0.3778 | 100% |
| unicode61 + Jina RRF | 0.1583 | 0.2278 | 100% |
| 子词 + Jina RRF | 0.1560 | 0.2333 | 100% |

沿用词表后，MiniLM nDCG 为 0.2200、Jina 为 0.2189。新 Jina 在历史题上的明显优势没有稳定复现：G2–NAVI 6 个正例组中 MiniLM / Jina 为 0.3236 / 0.2410，G2–Aurora 9 个正例组为 0.1222 / 0.2081。两场的方向不同，不能用整体均值宣布模型普遍领先，也不能把语言变体或地图当成独立比赛样本计算显著性。

生产受限关系路径单独验证：60/60 表述、780/780 项状态 / 数值 / 事件证明 / API / 混合调用层检查通过，15 个无答案组均未返回伪关系证据。这里从原始自然语言提取主体和条件，再扫描源事件。该成绩属于确定性查询与接口契约验收，不是 RRF 分数，不与文本排序做“图算法提升百分比”的因果解释。所有正例自然包含至多 3 个相关回合，未在选择时截断标签。

共 960 条文本结果已逐项核算范围、去重、Recall 和 nDCG；首次失败原样保留。远程模型调用 0，未调整模型、阈值或问题以改善本轮分数。

## 复现与边界

在冻结提交 `8160af0` 使用独立新输出文件执行：

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m scripts.evaluate_relation_queries \
  --protocol datasets/evaluation/isolated_relation_v1_engine_protocol.json \
  --output data/evaluation/isolated_engine_reproduction.json
PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.evaluate_language_baselines \
  --protocol datasets/evaluation/isolated_relation_v1_text_protocol.json \
  --output data/evaluation/isolated_text_reproduction.json
```

原始 Demo / 模型本地保留，哈希与取得来源进入清单；本仓库不重新分发赛事录像或模型权重。准备脚本拒绝覆盖已存在目录。将来真正未见系列评测需要再冻结新的选择与问题，保持实现 / 参数不变。

## Review gate

- Verdict：通过（隔离工程与开发评测）。
- Findings：词表、融合、新模型均有退化实例；文本拒答缺口仍在。
- Verified：完整 2 系列 / 5 图 / 111 回合、666 个源事实组合、960 条指标核算、60 条生产关系表达与 780 项检查。
- Risks：只有两场已观察系列，来源选择题和 AI 标签存在共同解析偏差；主观教练质量尚无独立人工评分。
- Next actions：将当前结果组织为如实披露限制的展示材料；独立主观评价保持待评，不再在这些题上追分。

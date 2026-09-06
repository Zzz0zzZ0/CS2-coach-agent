# 历史数据重建与重新冻结 v2

后续更新：纯 Vector 的新增回归已完成 [正文实体与中文道具词形修复](VECTOR_EVIDENCE_IDENTITY_V3.md)，开发集恢复 50/50。下文 v2 数据修复与首次 49/50 的数字保留，便于复现。当前图谱仍为本轮 1,019 回合版本，Milvus 已进一步切换至补充战队正文的版本。

2026-09-07。原有 20 场、49 图保持不变，修正四张地图中被误当作正式回合的赛前刀局。SQLite 图谱与 Milvus 检索集合已完成候选构建、验收和切换；原有 8001 / 5173 服务未被停止。新增比赛继续隔离，不进入历史库。

| 项目 | 修正前 | 修正后 |
| --- | ---: | ---: |
| 历史回合 | 1,023 | 1,019 |
| 完整名单人次回合 | 10,230 | 10,190 |
| 图节点 / 边 | 48,643 / 144,281 | 48,600 / 144,098 |
| 图中战术银标 | 5,319 | 5,308 |
| Milvus 文档 | 1,121 | 1,117 |
| 选手 / 地图 / 系列 | 56 / 49 / 20 | 56 / 49 / 20 |

不是直接删除四条回合记录：全部 Demo 重新经过已修正的解析器，重建事件、战术标签、边、社区引用、检索文档与索引。四个有刀局的文件仍对应 2396948 Dust2、2396938 Dust2、2396945 Inferno、2396941 Dust2，回合编号及相关 ID 重新生成。

## Verdict

通过本轮历史数据修复的工程验收；纯 Vector 有一条检索类型回归，需继续修复。152 项离线测试通过；真实库、现有 API、全部选手分母与行为分组检查通过。

## Findings

数据一致性未发现本轮切换的高置信阻断问题。纯 Vector 的 `spirit_ancient_utility` 从旧集合的回合证据变为摘要 / 首杀证据，未通过类型检查（minor / high）；同代码对旧、新集合的 [复核](../datasets/evaluation/vector_rebuild_v2_diagnosis.json) 已复现，后续优先修复候选召回和排序。旧 benchmark 与旧引用依赖旧数据库快照，不能在新库上复用旧标签的回合 ID。旧 silver v0.2 更早包含 1,030 回合，不等同于切换前图谱的 1,023 回合；两个历史版本均保留。

## Verified

- [图谱审计](../datasets/evaluation/historical_rebuild_v2_report.json)：49 图与冻结的原始 Demo 边界清单一致，1,019 回合编号连续、名单完整，事件和阵容位于正式开局边界之后；悬空边、回合事件路径错误均为 0。
- [选手行为审计](../datasets/evaluation/player_behavior_v2_audit.json)：56/56 名选手通过；六类行为的有/无观察分组、胜负、分母和引用由原始名单及事件边复核。
- [向量库核对](../datasets/evaluation/vector_rebuild_v2_report.json)：1,019 条回合证据、49 条摘要、49 条首杀摘要。文档逐字段等于新 Demo 解析结果，全部回合正文与图谱对应事件一致。
- [派生数据一致性](../datasets/evaluation/historical_derived_consistency_v2.json)：silver v0.3 的 5,308 个标签与图谱内容逐条相同；28 个社区引用无失效回合。silver 事件数为 42,148，缺失证据、重复事件 ID、tick 越界均为 0。
- [现有 API](../datasets/evaluation/historical_rebuild_v2_api_report.json)：8001 返回新图统计，56 名选手分母与候选库相同，合计 10,190 人次回合。
- [端到端回归](../datasets/evaluation/cs2_coach_rebuild_v2_report.json)：结构化契约 50/50，Graph / Hybrid 检索 50/50，纯 Vector 49/50（151/152 检查点），保留失败记录。
- 本轮没有远程 LLM / 提供商调用。嵌入使用本地缓存模型，Milvus 为本地服务。没有增加定时任务或登记团队知识库。

## Risks

SQLite 与 Milvus 无共同事务；此次先保留旧集合再更名新集合，最后原子替换 SQLite 文件，两个步骤间存在短暂版本过渡窗口。切换后已核对现有 API 与完整集合。原来已生成的任务报告不会被改写；复现旧报告应使用旧数据快照。

AI 标签沿用既有问题语义与审核条件，仍与被测方法共享解析来源，且开发问题已经看过。重新冻结消除了已确认的刀局污染，不证明所有解析事实均正确，也不替代人工视频核对、盲评或未见比赛泛化测试。

## 重新冻结的检索实验

[语料清单 v2](../datasets/evaluation/fair_corpus_manifest_v2.json)、[AI 标签 v2](../datasets/evaluation/fair_ai_qrels_v2.json) 在此次新排序运行前生成。沿用原有 16 题及相同审核条件，11 题有答案、5 题无答案；新的 [160 条排序报告](../datasets/evaluation/fair_ai_retrieval_v2_report.json) 确实重新编码并检索，不复用旧排序。保持原来的精确实体过滤和基线，便于区分数据修正与后续算法变化。

| 方法 | 无实体条件 nDCG@5 | 有实体条件 nDCG@5 |
| --- | ---: | ---: |
| BM25 | 0.6580 | 0.6425 |
| Dense | 0.5636 | 0.9099 |
| Dense + BM25 RRF | 0.8301 | 0.8226 |
| SQL 事件参考 | 0.4545 | 1.0000 |
| 回合→事件路径参考 | 0.4545 | 1.0000 |

均值分母为 11 个正例；5 个负例的误召回为无实体条件 3/5、有实体条件 0/5。SQL / 路径参考额外获得事件条件，不代表生产 GraphRAG，不能用此表声称其优于文本方法。BM25 的中文分词、精确实体别名遗漏，以及 MiniLM 的分块表示仍待校准。本机运行同时有其他验收工作，耗时只留作本轮记录，不用于性能提升结论。

## 回退与复现

[切换清单](../datasets/evaluation/historical_data_promotion_v2.json) 保存前后哈希及备份位置：

- 旧 SQLite：`data/evaluation/historical_rebuild_v2/graph_before.sqlite`，SHA-256 `6128fa1036a19ad661a9277a338b65fe662c149d3e5c85a2f75ff1d2325b0aab`。
- 新 SQLite：`data/graph/cs2_graph.sqlite`；候选副本仍在 `data/evaluation/historical_rebuild_v2/graph_candidate.sqlite`，SHA-256 `28357be25a52d27b80e87a03ffcb2a545132c97d42632138ff60c47d67fc8c2d`。
- 旧 Milvus 完整集合：`cs2_tactical_knowledge_before_rebuild_v2`（保留原向量、主键和索引）；新数据使用原名称 `cs2_tactical_knowledge`。
- 旧语料与排序在 `data/evaluation/fair_v1/` 和原有 v1/v2 试跑报告中保留；新统一语料在 `data/evaluation/fair_v2/corpus.jsonl`。旧回合 ID 必须和对应语料哈希一起解释。

回退须同时恢复两种数据：先将当前 Milvus 更名到新的保留名称，再把旧备份更名为正式名称；保留当前 SQLite 后，将旧 SQLite 复制到同目录临时文件并原子替换。不要只回退代码或只恢复一种数据库。本轮验证了备份哈希、旧集合 1,121 条仍可读取；未为演练而再次切换服务。

候选重建必须选新输出路径；默认 `make seed` / `make graph-build` 会替换正式数据，不能用于保留快照的实验。此次新增 `--collection-name`，非默认集合名如果已经存在就拒绝运行。

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m scripts.build_graph \
  --demo-dir data/demos --db-path data/evaluation/reproduction/graph.sqlite
PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.seed_knowledge \
  --demo-dir data/demos --collection-name cs2_tactical_knowledge_reproduction
.venv/bin/python -m scripts.audit_historical_rebuild \
  --before data/evaluation/historical_rebuild_v2/graph_before.sqlite \
  --after data/evaluation/reproduction/graph.sqlite \
  --output data/evaluation/reproduction/graph_audit.json
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m scripts.audit_vector_rebuild \
  --graph data/evaluation/reproduction/graph.sqlite \
  --documents data/evaluation/historical_rebuild_v2/vector_identity_documents.jsonl \
  --collection cs2_tactical_knowledge_reproduction \
  --output data/evaluation/reproduction/vector_audit.json
make silver-dataset ARGS="--output-dir data/evaluation/reproduction/silver"
make eval-fair ARGS="--corpus data/evaluation/fair_v2/corpus.jsonl --queries datasets/evaluation/fair_queries_v1.json --qrels datasets/evaluation/fair_ai_qrels_v2.json --allow-ai-reviewed --output data/evaluation/reproduction/fair_report.json"
```

`make silver-dataset` 默认版本改为 v0.3，已有目录拒绝覆盖；需要新的复现目录。数据和模型缓存需另行取得，源码仓库不包含数据库或 Demo。

## Next actions

在修正后的开发语料上校准中英文文本基线与实体别名处理，并按语言分层报告；保持数据、问题和 AI 标签不变，将算法变更作为下一组独立比较。随后补充整场隔离的检索评测及 Coach 建议质量审核，最后组织求职和港硕申请材料。

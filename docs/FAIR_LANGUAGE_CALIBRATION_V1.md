# 中英文与别名校准 v1

本轮是已观察开发语料上的受控实验。固定 1,019 回合、原有 16 个语义问题，补齐中英文共 32 个表述；两种语言共享相同参赛主体、事件定义、范围和相关回合。翻译与标签均由 AI 辅助审核，不属于人工 gold。

当前已冻结 [运行协议](../datasets/evaluation/fair_calibration_v1_protocol.json)、[成对问题](../datasets/evaluation/fair_paired_queries_v1.json)、[逐源标签](../datasets/evaluation/fair_paired_qrels_v1.json) 与 [适配配置](../datasets/evaluation/fair_query_adapters_v1.json)。逐题翻译核对在冻结前纠正过一处无答案题的事件译法；最终 n04 的两种语言均问闪光致盲，不是下包。

四组设置在同一次运行中全部报告：原始查询 + 精确实体、术语补充 + 精确实体、原始查询 + 别名、术语补充 + 别名。每组同时运行无实体约束和有实体约束的 BM25 / dense / RRF，以及单列 SQL / 回合事件路径参考，共 1,280 条结果。结构化参考额外得到 event_kind，不代表生产 GraphRAG。

正文为英文，所以中文适配采用固定 CS2 术语补充，保留原自然语言查询；BM25 与 dense 接收相同适配文本。它不是通用中文分词器或翻译器，也不读取标签、事件槽、比赛 ID 或 query ID 生成检索词。实体别名来自此前已审核的 Spirit / Team Spirit、Falcons / Team Falcons 等价关系，仅做完整名称匹配，不把 Academy 等相似名称合并。

不根据结果调词表、top-k、融合参数或阈值。先检查原 160 条排序与前一版逐条相同；分语言报告时各有 11 个正例、5 个负例，合并报告先按语义问题平均，不能把译文当作额外独立样本。候选相关回合的覆盖率与最终 top-k 排序分开分析；别名补全不保证 nDCG 上升。

生产 SQLite / Milvus 不写入，常驻服务不重启，文本模型调用为 0。语料向量使用相同本地模型与分块方法，要求 SHA 与前一次冻结结果一致；本轮还会保留逐题有效查询、来源 ID 与分数。

```bash
PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.calibrate_fair_retrieval \
  --protocol datasets/evaluation/fair_calibration_v1_protocol.json \
  --model-dir /absolute/path/to/the/frozen/local/model \
  --output data/evaluation/calibration_reproduction/report.json
```

输出必须是新路径，协议验证输入、源码和模型哈希。源码修改后需要检出该冻结版本或建立新协议。复现需要本地 1,019 回合语料、图谱及对应模型缓存。

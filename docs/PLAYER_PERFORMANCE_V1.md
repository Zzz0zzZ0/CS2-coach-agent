# 选手画像查询性能核验

Profiler 显示，每次 `player_context` 都在读取某个选手的指标前遍历所有 42,148 个事件，反复规范化其他比赛的战队字段。3 次 donk / Nuke 查询中，战队规范化路径占主要累计耗时。优化仅提前跳过完整名单已确认该选手未参赛的回合；名单不完整时仍保留原有事件推断，不增缓存、依赖或持久索引。

`9eb0e86` 冻结实现及核验协议，使用 `8160af0` 中的原文件作对照。56 名选手 × 4 种条件（全部、Nuke、T、对手 Falcons）共 224 组查询，交替执行优化前后版本，两个客户端先预热画像缓存：

| 核验项 | 结果 |
| --- | ---: |
| 完整 JSON 输出完全一致 | 224/224 |
| 原实现耗时中位数 | 335.31 ms |
| 新实现耗时中位数 | 104.08 ms |
| 配对加速比中位数 | 3.29× |

按两组耗时中位数比较约下降 69%；这是本机一次交错运行的描述，不是并发容量、冷启动或跨硬件性能保证。CPU profile 带探针开销，因此不拿 profile 的绝对耗时计算提升。完整结果和输入哈希见 `datasets/evaluation/player_performance_v1_report.json` / `_protocol.json`。

复现前在新的本地文件导出原实现 `git show 8160af0:app/services/graph_rag_service.py`，核对协议中的 SHA256，再用 `.venv/bin/python -m scripts.check_player_performance --protocol ... --output <新文件>`。不会修改原始图谱、模型或向量索引。

## Review gate

- Verdict：通过（数据等价与本机性能范围）。
- Findings：优化只提前排除已有逻辑最终也会排除的完整名单非参赛回合。
- Verified：224/224 完整 JSON 等价，261 项离线测试，包括缺失名单、替补与跨队范围；测量前后历史图谱哈希固定。
- Risks：仍扫描事件行，现规模可用；更大语料应先重新测量，不能用缓存掩盖不明确的数据失效边界。
- Next actions：保留基线及结果，常驻进程加载后继续使用原有接口。

普通检索回归通过：结构化契约 50/50，三模式开发查询 50/50；旧 holdout 为 Vector 28/30、Graph 30/30、Hybrid 30/30，与优化前相同。报告保存在 `datasets/evaluation/player_performance_v1_legacy/`。

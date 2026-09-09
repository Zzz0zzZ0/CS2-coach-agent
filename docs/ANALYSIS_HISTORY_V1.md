# 真实执行事件与持久化分析记录

2026-09-09。完成运行机制改进的两项 P0：页面展示实际节点事件，分析结果持久保存到本地 SQLite。保留 Python / LangGraph / Celery，没有引入新的框架、消息通道或依赖。借鉴 [Pi 的执行事件与上下文接口](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)及[会话持久化](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md)的设计思路，未复制其代码或移植通用 coding agent。

## 实现与读取

- 共用工作流记录每个节点的 started / completed / failed、时间、耗时、执行次数；Retrieve 再次执行会产生独立事件。另记录 Parse 与客户端 Initialize 阶段。
- 节点完成事件按用途记录回合数、检索数量、工具结果概要、模型选择来源及 usage、Verifier 结果。只有实际执行过的节点才能显示完成；规则 Coach 明确显示为规则建议。
- `AnalysisResult` 保留 execution_trace、retrieval_trace 和 tool_trace。页面的十个阶段不再按整体 SUCCESS 统一点亮。
- `ANALYSIS_RUN_DB` 默认 `data/runtime/analysis_runs.sqlite`，相对路径按项目根目录解析。保存任务 ID、输入 metadata、Demo SHA-256、规范化 payload SHA-256、解析后 payload、开始时 Git 提交、事件、完整报告与引用。输入快照只保存在本地，不通过任务读取接口返回。
- `GET /api/tasks?limit=20` 返回最近记录，最多 100 条；页面提供“已保存分析”选择。`GET /api/tasks/{id}` 优先读 SQLite，没有本地记录的旧任务继续使用原 Redis 路径。读取记录不会启动流水线。
- 原始 Demo 不自动归档；上传副本仍按原规则删除。这里的持久化是解析输入、运行事件和结果，不是录像备份。

## 故障与重复投递

任务开始时原子占用 task_id，多个连接竞争只有一个成功。已成功任务重复投递直接返回已保存的完整结果，不初始化模型、不再解析文件。已有失败或执行中记录的任务拒绝自动重跑。新 task_id 仍表示新的分析，输入哈希不用于自动跨任务去重。

节点异常保存错误类型及此前事件，不将原始错误正文写入运行记录。失败后的节点没有伪造事件。进程被强行终止可能留下 STARTED；页面明确提示“最近一次事件不代表 Worker 仍在线”。本阶段没有心跳检测、阶段自动续跑或付费请求自动重放。SQLite 不可读返回 503，避免把损坏记录伪装成新任务。

这些记录属于本地项目运行数据，不登记对话或团队知识库。记录保留到运维明确处理为止，目前没有自动清理策略；本地磁盘损坏、手动删除记录、数据库与代码不匹配仍需备份处理。Git 提交用于标识运行版本；运行时未提交的修改、全部依赖及检索库版本尚未形成完整环境快照，因此不宣称跨环境逐字复现。

## 验收

276 项离线测试通过，前端构建通过。新增 7 项行为测试覆盖：

1. 完整报告与输入指纹保存，读取不接触 Redis，重复执行不初始化模型。
2. 节点执行未结束时，独立连接已经能读到 started 事件。
3. Coach 异常保留此前进度，不出现 Verifier 完成，也不把错误正文写入历史。
4. 两个连接争用同一任务，只有一个获得执行权；中断记录不自动恢复执行。
5. Demo 解析失败留下失败事件与输入哈希。
6. 检索重试的 attempt 和耗时分别记录。
7. 历史读取不创建空数据库，损坏存储返回 503，列表限制生效。

真实运行使用已有 G2–Aurora Mirage Demo，经浏览器上传、常驻 API / Celery、真实 Milvus / Graph 与规则 Coach 完成。任务 `c47e2e3d-b137-40e6-9585-8cd7f4d36f2f`：14 回合、G2 13:1 Aurora、97 次有效击杀，15 条当前证据、12 条历史证据，Verifier pass。保存 20 条真实事件，十个阶段的页面状态与记录一致，全文和历史选择 / 刷新恢复核对通过。

第一次页面核验发现 FLOW 中旧名称 `RAG + Graph` 未对齐后台 `Retrieve`，导致该节点未点亮；已修正映射，用同一真实报告重新核验，无需重新分析。首次失败脚本输出保留。

另仅移除该验收任务的 Redis 结果缓存（原值已本地备份），API 仍从 SQLite 返回完全相同记录。在上传副本已经删除的情况下，用相同 task_id 再投递一次：Worker 返回原结果，运行记录、事件数量和模型账本均未改变。没有停止 Redis 或删除其他任务缓存。

本次模型预算始终保持暂停；新增远程模型调用 **0**，账本仍为 4 次尝试、3,317 已报告 tokens、5,456 未结算预留。它验证的是新事件与恢复机制，云模型能力沿用 [此前两次真实验收](LIVE_E2E_V2.md)，不能把本次规则运行称为新的云模型验收。历史图谱 SHA-256 不变；未摄取知识。

制品在 `data/evaluation/analysis_history_v1/`。任务原始 JSON、截图、缓存备份、浏览器脚本与运行数据库留在本地；Git 保存 [验收摘要](../datasets/evaluation/analysis_history_v1_report.json)。后续 P1 为结构化事实核验与受限追问，本阶段不包含这些能力。

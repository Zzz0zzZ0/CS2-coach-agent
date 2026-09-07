# 真实上传链路验收与连续任务修复

更新：修复后的两次连续云模型验收现已通过，见 [v2 结果](LIVE_E2E_V2.md)。以下保留首次运行时状态与失败记录。

2026-09-07。使用已有 G2–Aurora（2396944）Mirage Demo，不下载新比赛，不摄取知识。机器可读结果见 [验收报告](../datasets/evaluation/live_e2e_v1_report.json)。

## 结论与边界

在 `1c88d8f` 的常驻服务上，Playwright 驱动真实 Chrome 文件输入和提交按钮，经 Vite → FastAPI → Redis/Celery → demoparser2 → LangGraph → Milvus / SQLite Graph → DashScope → Verifier 完成一次真实任务。没有替换接口或模型响应。随后浏览器从真实任务 API 重新载入该结果并核对全文与证据。

第二次真实上传暴露连续任务的异步连接生命周期缺陷。已修复并通过两次连续本地 HTTPS / 真实 SDK / 完整 AnalysisPipeline 调用及离线回归；**修复后没有再次调用远程模型**，因为第二次失败触发既定预算停止机制。首次完整链路成功、修复验证和当前暂停状态分别记录，不合并表述为最新代码连续两次云模型成功。

| 项目 | 实际结果 |
| --- | --- |
| 首次任务 | `9c50fde9-6b5e-4876-8bf1-011694550995`，Celery SUCCESS，分析 success |
| 真实输入 | 14 个正式回合，G2 13:1 Aurora，97 次有效击杀，14 次首杀 |
| 检索结果 | 15 条当前证据；12 条历史证据，其中 Milvus 6 条、Graph 6 条 |
| 模型 | `qwen3.8-flash`，`selection_source=qwen_tool_call`；输入 852 / 输出 140 / 合计 992 tokens |
| 引用检查 | Verifier pass；无未知引用、缺引用声明或缺失报告 |
| 二次任务 | `80f54178-4f66-4266-92cc-e35baa25232f`；模型失败，规则报告完成且 Verifier pass |
| 页面核验 | 首次真实报告两段全文与 API 完全一致，27 条证据，992 tokens、PASS；刷新后仍能读回 |
| 数据保护 | Graph SHA-256 不变；Milvus 仍为 1,117 条；知识任务 0；两个临时上传副本均已删除 |
| 回归 | 262 项离线测试、前端构建、pip check 通过 |

模型只选择白名单训练优先级，报告事实由确定性代码生成。本例检索确实执行，但最终 Analyst / Coach 文本只引用当前 `[C#]`，未引用历史 `[E#]`；不能宣称历史检索改善了建议质量。单张已观察地图不构成泛化、吞吐或真人教练质量证明。

## 发现的问题与修复

1. 首次任务已成功，但临时浏览器脚本用精确文本 `已完成` 匹配包含任务 ID 的整行，截图检查失败。原始任务与脚本保留，后续改为匹配 `.task-line`；没有将脚本失败冒充应用失败。
2. 第二次模型请求在约 1.5 ms 内失败。原调用包装器只保留安全原因码 `request_failed`。在本地 HTTPS 服务中使用同一 ChatOpenAI 客户端、预算包装器和完整流水线，复现第一次成功、第二次 `APIConnectionError`，原因为 `RuntimeError: Event loop is closed`；普通 HTTP 对照未复现。该实验支持缓存 TLS 连接跨已关闭事件循环的诊断；原生产异常链未保存，不能声称已从生产堆栈直接读到根因。
3. `app/services/tasks.py` 改为在 Celery solo / prefork 的同步执行槽内缓存 `asyncio.Runner`，与已缓存的客户端共用生命周期。当前运行方式每个进程一个同步执行槽；没有验证 threads / gevent pool。`test_worker_lifecycle.py` 在真实任务入口连续执行两次，修复前第二次回退，修复后两次模型路径成功、账本完整结算。本地 HTTPS 复现实验同样由红转绿。
4. 页面原先刷新即丢失任务。成功提交后将任务 ID 写入 URL，页面从 `?task_id=` 只读恢复任务；不重复提交文件或重新调用模型。真实任务读回、刷新、全文一致及零 POST 已核验。结果受 Redis 的保留期限约束，不是永久报告存档。

## 当前预算状态

保留两次尝试：已报告 992 tokens，失败请求另保留 5,456 tokens 未结算预留；本地剩余预留额度 23,552 / 30,000，`status=stopped`、`stop_reason=request_failed`。未知用量未记为零，失败记录未清空，未切换模型、自动重试或提高额度。提供商剩余余额未知。

当前可展示已保存的真实结果，并继续离线验收。修复后的远程复测需要先按 [预算边界](MODEL_BUDGET_BOUNDARIES.md) 处理失败请求的用量与恢复授权，不属于本记录已通过的项目。

## 本地制品与只读查看

完整任务 JSON、原始失败脚本、浏览器截图、页面文本、本地 HTTPS 复现脚本及前后数据核对保存在 `data/evaluation/live_e2e_v1/`，未将 Demo、密钥、测试证书或原始模型报告加入 Git。提交的 JSON 记录结果摘要与制品哈希。

服务运行且 Redis 结果未过期时，打开 `http://localhost:5173/?task_id=9c50fde9-6b5e-4876-8bf1-011694550995` 即可只读恢复首次真实报告。当前预算横幅展示最新暂停状态，报告中的 992 tokens 是首次任务用量，两者时间范围不同。

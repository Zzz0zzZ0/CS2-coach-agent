# 连续真实上传全链路验收

2026-09-07，代码 `e48e570`。结论：**两次连续真实上传均通过**，修复后的同一常驻 Celery Worker 连续调用 DashScope 成功。机器可读结果：[完整核验](../datasets/evaluation/live_e2e_v2_report.json)。[首轮失败与修复记录](LIVE_E2E_V1.md)继续保留。

## 实际链路

Playwright 驱动真实 Chrome 的文件输入与“开始分析”按钮，上传已有 G2–Aurora（2396944）Mirage Demo，依次经过 Vite → FastAPI → Redis / Celery → demoparser2 → LangGraph → Milvus / SQLite Graph → `qwen3.8-flash` → Verifier → 浏览器报告。没有替换接口响应或调用本地假模型。两次运行之间未重启 Worker。

| 核验项 | 第一次 | 第二次 |
| --- | --- | --- |
| 任务 ID | `1e5668e3-e219-4e1e-beb0-511b4c9c8e1e` | `2c13f49b-3395-4ef1-998e-f2f731268280` |
| 任务 / 分析状态 | SUCCESS / success | SUCCESS / success |
| 正式回合 / 比分 | 14 / G2 13:1 Aurora | 14 / G2 13:1 Aurora |
| 有效击杀 / 首杀 | 97 / 14 | 97 / 14 |
| 当前 / 历史证据 | 15 / 12 | 15 / 12 |
| 历史来源 | Milvus 6 + Graph 6 | Milvus 6 + Graph 6 |
| 模型选择来源 | qwen_tool_call | qwen_tool_call |
| 输入 / 输出 tokens | 852 / 430 | 852 / 191 |
| 合计 tokens | 1,282 | 1,043 |
| Verifier | pass | pass |
| 页面全文、27 条证据、刷新恢复 | 通过 | 通过 |

两次模型合计用量 **2,325 tokens**。Worker 日志只有一次启动，两个 DashScope HTTP 200；没有第二次请求失败、自动重试或模型切换。页面刷新仅 GET 既有任务，不增加模型调用。

## 预算恢复与停止

操作前备份生产 SQLite 账本。经明确授权，为唯一已结束的 `request_failed` 请求记录两次恢复窗口。原 calls 行逐字段与备份一致，旧失败的 **5,456 tokens 未知用量全部继续占用预留**，没有将其记成零或伪造提供商 usage。恢复记录单独保存授权说明、时间、请求 ID 与次数上限。

最终生产账本累计 4 次尝试，已报告 3,317 tokens（原成功 992 + 本次 2,325），未结算预留 5,456，剩余本地额度 21,227 / 30,000。总预算与原 100 次上限未增加。`accounting_complete=false`，提供商剩余额度未知。

两次授权窗口用完后返回 `recovery_call_limit_reached`，因此当前模型调用暂停；这是授权次数耗尽，**不是本轮请求失败**。没有发起第三次远程验证。规则分析和已有报告查看继续可用。恢复边界与拒绝条件见 [模型预算说明](MODEL_BUDGET_BOUNDARIES.md)。

## 保护与回归

- 图谱 SHA-256 保持 `28357be25a52d27b80e87a03ffcb2a545132c97d42632138ff60c47d67fc8c2d`，Milvus 仍为 1,117 条；未下载比赛或摄取知识。
- 两个临时上传副本自动删除，原 Demo、原失败结果及账本备份保留在本地。
- 269 项离线测试、前端构建通过。恢复用例覆盖预留和失败行不变、次数用完停止、新失败停止，以及拒绝 pending / 提供商拒绝 / 用量缺失 / 取消等非目标状态。
- 本地与远端旧分支 `codex/graphrag-player-analysis`、`codex/recovery-20260906` 已删除；删除前确认四个本地 / 远端 tip 都是 main 的祖先。现仅保留 main，原提交历史仍可回退。

## 查看与材料边界

服务运行且 Redis 任务未过期时，可打开 `http://localhost:5173/?task_id=2c13f49b-3395-4ef1-998e-f2f731268280` 查看第二次真实报告。完整本地制品在 `data/evaluation/live_e2e_v2/`，提交 JSON 记录摘要与哈希；没有将密钥、Demo 或原始模型报告放入 Git。

本次证明的是一张已观察地图上的完整应用链路及连续任务修复。最终文字只引用当前证据；历史检索确实执行，但不能据此声称提高建议质量。模型仅选择白名单优先级，报告事实由代码生成；不构成独立真人教练评价、泛化或吞吐证据。

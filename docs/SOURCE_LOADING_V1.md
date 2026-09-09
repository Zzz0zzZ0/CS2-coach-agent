# 当前比赛来源按需加载与上下文隔离

2026-09-09。P2 范围限于当前比赛追问的来源加载；不增加模型规划、持久聊天、跨比赛缓存或依赖。已有完整分析入口、报告格式和查询结果保留。

## 实际问题与改动

V1 列表追问在用户未展开来源时，也返回全部选中回合的击杀序列与事件正文。页面现在先请求摘要，点击某个来源时再通过已有回合查询读取正文；同一回答中已加载来源重新展开时不再请求。直接问某一回合的意图就是查看详情，因此仍一次返回完整数据。

服务端只构造选中来源的正文，继续复用既有指标与证据生成逻辑。每次查询仍会读取、核对整份输入并计算整场指标；本轮没有减少整场计算、初始报告加载或模型上下文。

新增可选参数：

```text
GET /api/tasks/{task_id}/questions?kind=opening_losses&detail=compact
GET /api/tasks/{task_id}/questions?kind=round&round_number=2&expected_payload_sha256={64位小写SHA256}
```

默认 `detail=full` 与 `dab9ec1` 的完整响应保持一致。`compact` 仅去除来源的 `content` 和回合事实的 `kill_sequence`，保留状态、全范围计数、选手聚合、来源标识、引用、元数据和查询预算。步骤上限仍为每次 2 步，来源上限仍为 20 条。

页面初次追问绑定当前报告的输入 hash；来源展开也固定初始回答的输入 hash。服务端发现输入版本变化即返回 409，正文生成尚未开始。页面另核对 task ID、hash、source ID 和 citation；错误内容不会渲染。关闭来源、切换问题或切换任务会取消未完成的详情请求，迟到响应被忽略。失败保留明确错误和手动重试入口，成功内容只在当前回答中保留。

这些检查用于一致性，不构成本地数据库写权限之外的身份认证。

## 实测收益与代价

基线为 `dab9ec1`，使用已经观察过的 14 回合 G2–Aurora 保存任务。以下为 UTF-8 未压缩 JSON 正文大小，**不是整页流量、网络包大小、耗时或模型 token**。

| 查询 | 原完整响应 | 页面首次响应 | 首次减少 | 若全部展开的总正文 | 额外详情请求 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首杀后失利（4 个来源） | 10,357 B | 3,463 B | 66.56% | 15,779 B | 4 |
| 下包后失利（1 个来源） | 3,292 B | 1,476 B | 55.16% | 4,673 B | 1 |
| R1 | 2,848 B | 2,848 B | 0% | 2,848 B | 0 |
| Wicadia（13 个来源） | 11,150 B | 4,646 B | 58.33% | 42,802 B | 13 |

收益适用于浏览列表、只展开少量来源的交互。全部展开会增加总请求和传输量，尤其选手问题会额外获取逐回合完整事实。需要全部数据的调用者继续使用默认完整接口。该单场开发测量不支持吞吐、整体加速或泛化声明。

## 验收与复现

352 项离线测试通过，其中 27 项为新开发用例；前端构建通过。四类默认完整响应与原实现逐对象一致，展开来源与完整响应一致；独立审查另核对 2 份保存输入、28 回合的完整来源一致。

真实浏览器验证了：

- 折叠时无详情请求；首次展开读取一次，再展开不重复；单回合查询不追加请求。
- 错误 source ID 被拦截，手动重试恢复。
- 人为延迟的详情请求在切换问题/任务后被取消，旧内容未进入新页面。
- 版本不匹配返回 409；四类查询和 390px 手机布局可用；页面异常和写请求为零。

历史记录库、历史图谱、模型预算账本的文件 SHA256 前后均未变化，本轮新增远程模型调用 0。既有模型暂停状态维持，未重新上传 Demo 或执行分析。

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
mkdir -p data/evaluation/source_loading_reproduction
git show dab9ec1:app/services/followup_service.py > data/evaluation/source_loading_reproduction/baseline.py
.venv/bin/python -m scripts.check_followup_loading \
  --task-id b0171fbf-18c5-4aa1-ad0b-a052ab52169e \
  --baseline-source data/evaluation/source_loading_reproduction/baseline.py \
  --output data/evaluation/source_loading_reproduction/result.json
```

最后一条命令需要本机已有对应保存任务；其他环境用自己的已完成任务 ID，结果大小会不同。脚本禁止网络并拒绝覆盖旧输出。输入库文件若在测量中变化则检查失败。

[可分享验收摘要](../datasets/evaluation/source_loading_v1_report.json)包含具体响应体积、浏览器检查和源码 hash。原始运行日志、请求记录与截图位于本地 `data/evaluation/source_loading_v1/`；这不是独立教练质量或未见比赛 benchmark。

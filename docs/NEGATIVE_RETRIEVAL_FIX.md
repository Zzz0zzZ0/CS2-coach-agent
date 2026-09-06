# 负例检索边界修复验收

## Verdict

通过。本轮增量修复满足原始三类负例拒答要求，最终 Graph/Hybrid 27 个既有正例无损失。范围为本轮查询约束、检索和评测退出码改动；不等于对工作区所有历史未提交改动作全面审计。

## Findings

未发现本轮增量的高置信阻断问题。修复了以下已验证行为：

- 英文名称、名称与地图、对手和比较句式的未知实体不再被当成可忽略关键词。Graph 从现有索引核对实体，Vector 要求候选证据包含完整名称；相似昵称不能冒充。
- 缺少显式上下文时，`match`、`professional` 等通用词不再单独放行；显式地图/比赛过滤保留原有上下文意义。
- 图本地检索先按实体过滤，再截取 top-k；全局检索对不存在的主体拒答，已知主体的画像与地图社区背景保留各自语义。
- 评测 CLI 的检索失败现在能返回非零退出码，避免只通过结构化契约就误判整次验收成功。

## Verified


| 模式 | 修复前查询 | 最终查询 | 最终检查 | 最终综合分 |
| --- | ---: | ---: | ---: | ---: |
| No RAG | 3/30 | 3/30 | 3/99 | 5.37 |
| Community only | 11/30 | 14/30 | 64/99 | 46.31 |
| Vector only | 24/30 | 27/30 | 96/99 | 67.79 |
| Graph only | 27/30 | 30/30 | 99/99 | 100.00 |
| Hybrid | 27/30 | 30/30 | 99/99 | 100.00 |


- 独立开发负例：12 条，修复前定向测试全部失败，修复后真实 Vector/Graph/Hybrid 均为 12/12。
- 原开发检索：Vector/Graph/Hybrid 均为 50/50；结构化契约为 50/50。
- 最终全量测试：80 passed，3 warnings；覆盖中文别名、ASCII handle、比较中的未知对象、相似昵称、显式地图上下文、match_id、本地 top-k 以及既有闪光归因用例。
- 已运行 `make test`、`make eval-rag`、`make eval-v1`、`make eval-negatives`、`make eval-holdout`、`make frontend-build` 和 `git diff --check`。
- 评测显式关闭辅助 LLM 调用，使用本地 FastEmbed；远程模型调用及 token 均为 0。全量测试最终运行使用空环境密钥和不存在的临时运行时密钥路径。
- 原始基线保持原样。冻结查询 SHA-256：`ab5991b913c26bf7dd44c071c271e258cd141bbf1c78a8c15c81b0d85756f435`。
- 没有重建图谱、重灌向量库、重新下载 Demo、新增依赖或改动模型选择。运行中的 API/Worker 未重启，验证针对本地源码执行。

### 复测过程完整性

原计划只复测一次，但第一轮未通过：Graph 26/30、Hybrid 27/30，虽然原有三个负例已正确拒答，却出现了正例回退。错误来自名称语法过宽、地图上下文被忽略以及过度过滤地图背景。该失败报告保留为 [`cs2_coach_holdout_v1_attempt1_report.json`](../datasets/evaluation/cs2_coach_holdout_v1_attempt1_report.json)。

随后用独立描述句与地图上下文用例复现，收窄名称语法并恢复原有上下文与社区职责，再运行开发集和第二次最终验收。**实际 held-out 运行次数为 2**，没有把失败结果覆盖后声称只运行一次。未修改冻结查询，也未在实现中加入冻结负例名称或跨领域短语特例。最终结果不应称为新的盲测。

## Risks

- Vector-only 仍有 3 条战术主题检查失败；与原始基线比较，没有已通过查询变为失败。Graph/Hybrid 覆盖了这些查询。
- 实体识别是有限 ASCII 查询语法，并非覆盖所有自然语言、多词队名、拼写错误和中英混合形式的 NER。调用方显式提供地图/比赛信息被视为可信领域上下文。
- 当前 30 条冻结查询仍来自同一批 20 场语料，且错误类别已公开；高分不证明未见比赛泛化，也不证明训练建议有效。
- 三项非阻断告警涉及 Starlette/AnyIO、FastEmbed pooling 和 Redis setex。尤其 embedding pooling 版本应在未来复现实验时固定。
- 全量测试和前端构建通过不等于运行中服务已加载新源码；本轮未执行部署或重启。

## Next actions

按 [项目改进路线](PROJECT_IMPROVEMENT_ROADMAP.md) 优先做独立比赛评测、公平消融、人工审阅和离线 CI。当前变更及原有工作区改动均保持未提交，未自动推送。

机器可读的前后对照、测试数量与源码哈希见 [`query_boundary_validation_v1.json`](../datasets/evaluation/query_boundary_validation_v1.json)。

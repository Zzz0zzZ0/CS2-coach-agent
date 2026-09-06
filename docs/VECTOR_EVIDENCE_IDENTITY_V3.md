# 回合正文实体与中文道具查询修复

历史数据切换后，纯 Vector 的 `spirit_ancient_utility` 从原先通过变为失败：查询“绿龙 Ancient 的道具协同”返回摘要 / 首杀证据，缺少回合证据。Graph / Hybrid 未失败。保留 [修复前 49/50 报告](../datasets/evaluation/cs2_coach_rebuild_v2_report.json) 和 [旧、新集合复核](../datasets/evaluation/vector_rebuild_v2_diagnosis.json)。

## Verdict

通过针对回合证据表示与查询词的修复验收。154 项离线测试通过；原失败用例现已通过。完整回归结果见下方报告。

## Findings

已修复（minor / high）：原始回合正文不包含该回合的战队身份，名称只在父摘要中；Milvus 搜索正文，而后置实体检查允许读取父摘要，形成候选召回与最终实体过滤的信息不一致。同时“道具”展开为单数 `grenade`，种子正文使用 `Grenades`，本地 BM25 对这种词形差异敏感。

证据来自固定查询的实际候选：前八项都是摘要或首杀证据。只去掉父摘要的词面加分不能修复，只补战队名称或只补复数词也不能修复。不是通过提高 top-k 或放宽测试要求解决。

## Verified

- `_round_content` 从当前回合实际名单去重读取战队名称，写入正文的 `Teams` 段，不从父摘要猜队伍。
- “道具” / “投掷物”中文展开同时保留 `grenade` 和 `grenades`；没有战队、比赛 ID 或单个问题专用规则。
- 1,019 条回合正文仅新增名单中的战队段；原事件正文、全部文档元数据、49 条摘要与 49 条首杀摘要不变。1,117 条候选文档经 [图谱与文本核对](../datasets/evaluation/vector_identity_v3_final_audit.json) 通过。
- 先保留 [仅补战队仍失败的结果](../datasets/evaluation/vector_identity_v3_repro.json)，再记录 [组合修复通过的原始用例](../datasets/evaluation/vector_identity_v3_corrected_repro.json)。两个单元测试先失败后通过，覆盖名单实体进入正文及中文道具词形传递到检索后端。
- [既有 holdout 回归](../datasets/evaluation/vector_identity_v3_holdout_regression_report.json)：Vector 28/30（此前 27/30），Graph / Hybrid 30/30。剩余 `h_team_vitality_dust2`、`h_para_nuke_round` 均为原有类型匹配失败，未出现新的失败用例；该集合已用于修复，不是盲测。
- [开发集回归](../datasets/evaluation/vector_identity_v3_dev_report.json)：结构化契约 50/50，Vector / Graph / Hybrid 检索均 50/50；原始 49/50 结果保留。

正式集合已切换，并通过 [逐字段核对](../datasets/evaluation/vector_identity_v3_live_audit.json)。修复前但已去刀局的集合保留为 `cs2_tactical_knowledge_before_identity_v3`；最早含刀局的完整备份 `cs2_tactical_knowledge_before_rebuild_v2` 也仍保留。参见 [切换清单](../datasets/evaluation/vector_identity_v3_promotion.json)。本轮远程模型调用为 0。

运行边界：正式 Milvus 已切换，当前源码通过新 Python 进程的真实 provider 查询验证。保留的 8001 Uvicorn 进程没有 `--reload`，本轮没有重启它或原有 worker；常驻进程中的新查询展开代码需在下次重启后加载。8001 已验证的是新图谱数据及画像分母，不是代码热更新。

## Risks

这是在已观察开发样本上修复的工程问题；回合补战队仍不等于为所有选手、语言和词形建立了完整检索表示。仍然需要更好的语言基线、明确实体约束的公平消融与隔离测试。本次没有修改 fair v2 的统一文本、标签或排序报告；生产检索修复与该独立实验分别记录。

旧图谱、旧解析集合及身份修复前集合保留。旧数据报告应按其代码版本复现：`41d671a` 的正文没有 Teams 段；当前向量核对工具会将正文渲染器源码哈希一并记录。换集合后新旧文档数都是 1,117，不能只凭数量证明切换成功。

## Next actions

继续在修正后的固定语料上校准中英文基线与实体别名处理，按语言分层报告。保留 AI 审核身份，不将这些开发回归写成独立 gold benchmark 或泛化结论。

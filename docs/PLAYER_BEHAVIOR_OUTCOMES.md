# 个体行为与回合结果 v1

选手画像新增 `behavior_outcomes`，将当前筛选内的参赛回合按某种个体行为是否被观测到分成两组。页面提供行为、引用结果筛选和回合时间线跳转；画像与选手对比 API 均返回同一份统计。此阶段不修改自然语言简报的总结逻辑，该项留在下一阶段。

## 行为口径

| key | 观测条件 | 来源 |
| --- | --- | --- |
| opening_kills | 该选手是标记为首杀事件的击杀者 | kill + KILLER + is_first_kill |
| opening_deaths | 该选手是标记为首杀事件的被击杀者 | kill + VICTIM + is_first_kill |
| trade_kills | 补枪标签中 trader_steamid 是该选手 | TRADE_KILL 银标；仅被补枪者不计入 |
| utility | 至少有一条属于该选手的道具事件 | grenade + THROWER；沿用现有解析的道具生效事件记录，不保证包含所有投掷 |
| flash_blinds | 至少有一条归属于该选手的致盲记录 | flash + FLASHER；包括可能的队友、自闪和多闪归因歧义，不等于有效助攻 |
| plants | 该选手是下包者 | plant + PLANTER |

## 分母和关联边界

- `baseline` 覆盖当前地图、阵营、对手筛选下的全部选手参赛回合，沿用名单确认或明确标记的旧数据估算。
- 每个行为的 `observed` 是观测到该行为的参赛回合集合；`not_observed` 是基线减去该集合。两组互斥且完整覆盖基线。不同的行为组可以重叠，不可把六类行为的回合数相加。
- 同一回合的多次道具、致盲或补枪事件只记一个行为回合，原有事件次数指标保持原意。
- 胜负按该选手当回合的历史队伍和阵营计算。`wins + losses + unknown = rounds`；`decided_rounds = wins + losses`；`round_win_pct = wins / decided_rounds × 100`。未知胜方不记作负，零分母为 null。
- `win_rate_difference_pp` 为已报告的两组胜率相减，单位为百分点；任一组无法计算时为 null。不生成能力排名、置信区间或显著性判断。
- 每种结果固定排序最多提供 3 条 `examples`，统计使用完整集合。引用不是随机抽样，不用于估计胜率；同时保留负回合，避免只看正面案例。
- “未观测到”不是“未发生”。两组未匹配经济、角色、时间和地图分布；事件可能发生在回合不同阶段，存在局势选择与反向关系，差值不是行为的因果收益。

## 复现与验收

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
.venv/bin/python scripts/audit_player_behavior.py --output /tmp/player-behavior-audit-new.json
.venv/bin/python scripts/evaluate_player_queries.py --output /tmp/player-behavior-query-new.json
```

审计脚本只读取当前图谱，依据底层事件边与完整名单复算各组计数、胜率和引用；缺少完整名单时报告无法使用名单审计，而不替估算值背书。它拒绝覆盖已有输出。不调用远程模型，也不修改图谱。它是工程一致性验收，不代替银标人工审核。

- 全套 **109 项离线测试通过**；新增用例覆盖历史队伍、替补缺席、未知结果、无样本、多事件去重、补枪角色及超过引用上限的统计。
- 真实图谱 **56 / 56 名选手**的六类行为通过原始记录审计，图谱哈希不变。NiKo 全范围基线 246 回合，121 胜 / 125 负；Nuke CT 基线 21 回合，17 胜 / 4 负。
- 既有选手查询 **20 / 20 通过**，数值和引用下钻无回退；前端构建通过。
- 浏览器检查行为切换、仅显示负回合引用、自动定位回合时间线以及筛选后的无行为样本显示。

制品：[原始记录审计](../datasets/evaluation/player_behavior_v1_audit.json)、[查询回归](../datasets/evaluation/player_behavior_v1_query_report.json)。前一阶段制品与未见比赛的旧实现冻结清单保留。

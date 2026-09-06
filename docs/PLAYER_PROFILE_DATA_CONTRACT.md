# 选手画像数据口径 v5

## 参赛分母

优先使用每回合 `round_freeze_end` tick 的名单，过滤为 T/CT 两侧、各 5 名唯一 SteamID。该口径表示冻结时间结束时在场，不宣称覆盖所有中途换人或重连情形。名单不足 10 人或侧别不完整时不会标记为完整。

`data_quality.confirmed_rounds` 表示名单确认的参赛回合；`estimated_rounds` 表示旧数据回退估算的回合。旧图谱不会被静默当作已核验名单。估算按该场地图的队伍记录进行，前端明确提醒其无法保证替补变化。

跨队选手按各场/回合的名单归属处理地图、阵营、对手与胜负筛选，不用其总体主队过滤全部历史。`teams` 返回当前样本中各队伍的参赛回合数。

## 零值与缺失

- 计数代表该范围内观测到的事件数；它本身不证明 Demo 解析所有事件完整。
- 分母为零时，K/D、首杀成功率、爆头率及每百回合指标不可计算，返回 null；前端显示“—”。
- 没有参赛样本时 `data_quality.status=no_sample`，不解释为选手表现为零。
- 名单确认只验证参赛分母，不等于战术银标正确或道具因果已获证实。

## 指标定义

| 指标 | 公式 / 含义 |
| --- | --- |
| K/D | 观测有效击杀 / 观测死亡；死亡为零时不输出有限比值 |
| 爆头率 | 爆头击杀 / 有效击杀 |
| 首杀成功率 | 首杀 /（首杀 + 首死） |
| 每百回合指标 | 对应事件次数 / 当前范围参赛回合数 × 100 |
| 战术参与 | 当前范围内关联的 silver label 次数；不等于人工确认角色或独立回合数 |

`sample_scope.match_ids` 给出完整样本比赛 ID。现有采集清单没有比赛日期字段，因此 `date_range=null`、`date_status=not_recorded`；不从文件修改时间或抓取时间伪造比赛日期。

## 迁移与验证

现有数据已使用 `scripts/enrich_player_rosters.py --apply` 补充名单。脚本在写入前检查全部地图的回合编号对齐并创建 SQLite 备份，然后在一个事务中更新名单。它不重建事件、战术标签、社区或 Milvus。

本轮 49 张地图、1,023 个回合均有完整名单；56 名选手合计 10,230 个参赛人次回合，事件参与者与名单冲突为 0，总览和上下文画像分母不一致为 0。原图谱节点与边总数保持 48,643 / 144,281。

证据见 [名单覆盖报告](../datasets/evaluation/player_roster_coverage_v1.json)、[画像口径审计](../datasets/evaluation/player_scope_audit_v1.json)和[开发评测](../datasets/evaluation/cs2_coach_player_p0_report.json)。

## 两名选手的样本对比

`GET /api/graph/players/compare` 保留 `players`，新增 `sample_comparison`；版本为 `shared-filters-descriptive-v2`。界面支持选择其他战队的选手，最多展示 API 当前上限 100 名；现有图谱有 56 名。双方使用相同地图、阵营、对手筛选，各自参赛回合为分母，不宣称筛选一致就构成公平能力比较。

- `sample_scope.composition` 按地图、阵营、对手集合联合分组，回合数合计等于该画像参赛分母。它展示分布，不做自动重加权。
- `sample_scope.participation_round_ids` 是完整参赛回合 ID，包含没有相关事件的参赛回合；`source_round_ids` 仍只是最多 12 条事件引用，不能用来计算共同参赛覆盖。
- `shared_match_ids` / `shared_participation_rounds` 表示双方共同参加的比赛 / 回合。直接交手的双方可以共同参赛，但所在阵营、对手不同。
- `shared_condition_count` 表示双方都有参赛样本的地图、阵营、对手组合数。`common_condition_coverage` = 各自落在共同组合中的回合 / 各自全部筛选回合，分母为零时为 null。替补与首发可以覆盖同一种条件，却没有共同参赛回合。
- 提示样本量不同、组成占比不同、无共同条件、估算名单或无样本。样本量没有被转换成“中 / 高置信度”；选手对比简报注明未进行统计推断。
- 界面同时给出 K/D 的击杀、死亡数和首杀成功率的机会数；共同覆盖率不表示样本已匹配、同日期、同经济条件或相同职责。

自然语言对比识别明确的 `对阵 / 对手 / against / versus / vs` 对手约束，同时应用于双方。仅提及两名选手所属战队不会自动限制对手。明确对手无法识别时不放宽到全部比赛；任一选手无样本时不生成对比简报。复杂自然语言仍需检查显示的筛选条件。

### 本阶段验收

- 104 项离线测试通过，包括替补错开参赛、跨队跨场、共同条件占比不同、零样本、旧分母与中英文对手约束。
- 真实图谱 56 / 56 名选手的组成合计、完整参赛 ID 数量与画像分母一致；图谱文件哈希未改变。
- 既有 20 条选手查询工程回归全部通过，保留旧报告；本轮不调用远程 LLM。
- 浏览器核验 NiKo / donk 跨队对比、组成展开以及对手筛选下的无样本说明；新请求会清除旧对比，失败展示错误。

报告：[样本审计](../datasets/evaluation/player_comparison_v2_sample_audit.json)、[查询回归](../datasets/evaluation/player_comparison_v2_query_report.json)。当前未实现日期校正、共同条件重加权、按比赛聚类的置信区间或能力排序。

## 个体行为与结果

画像新增 `behavior_outcomes`，包含基线和六种行为的互斥观测 / 未观测分组、胜负、未知结果、可下钻引用及描述性胜率差。详见 [行为与结果数据口径](PLAYER_BEHAVIOR_OUTCOMES.md)。原有每百回合事件次数指标保持原意；行为分组按唯一参赛回合计数。

## 确定性总结

`profile.brief` 与自然语言选手简报共用生成逻辑，结构化 `claims` 记录指标数值与引用所属分组，`sample_scopes` 记录基础指标和样本范围。无参赛样本时为 null。见 [总结契约](PLAYER_GROUNDED_SUMMARY.md)。

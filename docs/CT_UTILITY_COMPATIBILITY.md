# 投掷记录兼容诊断与部分恢复

更新：2026-10-26。该修复只影响情境侧的道具计数；冻结的共同输入、源模型权重和重建主结果保持原样。

## 官方版本记录说明了什么

上游没有独立的GitHub Release说明。本轮核对了[0.41.3至0.42.1的23个提交](https://github.com/LaihoE/demoparser/compare/54e320f381417b85c2b085921253499bacf9acdc...44f3a6cc97c62a9efc222fded1b986e034268821)：包含性能、玩家信息、UserCmd、实体句柄、字符串等修复；所查事件解码模块的事件名及字段名来自Demo描述表。未发现把`grenade_thrown`与`weapon_fire`互相更名的证据。这不排除未识别的兼容或录像差异。

实际区分三层：

| 层次 | 本轮观察 |
| --- | --- |
| 事件通道 | May样本没有暴露专用`grenade_thrown`，仍有`weapon_fire`及道具实体轨迹 |
| 字段和值 | 两通道都使用`weapon`列；`weapon_fire`值如`weapon_flashbang`，专用事件值如`flashbang` |
| 时间含义 | `weapon_fire`较早；专用投掷事件与原生道具实体首次出现时间一致；爆开另有`flashbang_detonate`等事件 |

旧May Dust2在0.41.3和隔离安装的0.42.1中均可读到带前缀的使用道具记录。之前按裸道具名检查备用通道会漏掉这些值；但仅去前缀仍不能把其时间当作出手时间。

## 游戏刻和实际例子

本例64刻/秒，1刻约15.625毫秒。October Dust2同一颗闪光依次记录在4000（`weapon_fire`）、4007（`grenade_thrown`）、4111（`flashbang_detonate`）刻。出手记录比第一条晚约0.109秒，爆开比出手晚约1.625秒。

该Demo全部535组动作的专用投掷记录比使用记录晚6—14刻，实体首次出现则全部与专用记录同刻。直接替换会使120个CT查询时刻中2处计数变化，因此不能把两个时间字段直接混用。

## 恢复规则与保留的未知

新脚本用原生`parse_grenades(grenades=False)`排除手持道具，识别实体首次出现，再与同玩家、同道具类别的使用记录按因果顺序配对。使用记录提供具体类型，实体提供时间；燃烧瓶和燃烧弹虽然共用实体类，仍按使用记录区分。玩家阵营及位置取实体出现时的原生状态，不套固定延迟。

录像全局缺一刻时，同一颗静止道具不算再次投出：仅在实体、玩家、类别、坐标未变，且间隔内没有新使用记录时接续。额外实体若出现在查询范围内，会按阵营标明不确定性；无法完整配对的Demo整体不派生。相关失败与修正均记录在修复协议中，没有按模型效果筛选。

12份Demo全部检查。8份有专用事件的对照，派生计数在828/830个CT查询时刻可核对且一致；2个有歧义的派生时刻未使用，其原有专用事件情境仍保留。三份旧May Demo恢复60个窗口，道具情境完整支持由166增至226/246。旧Inferno存在未配对记录，其20窗口继续未知。

修复前已支持的282,060个候选位置保持同一候选ID，距离在1e-10绝对容差内相等；3,566个原先情境已知的聚类分配保持相同标签与接受状态。排名变化仍没有新增人工相关性评分，稳定性不是战术正确率。

## 制品与重放

- [上游记录及单Demo事件时序](../datasets/evaluation/ct_utility_upstream_versions.json)
- [修复协议及失败记录](../datasets/selections/ct_independent_utility_repair.json)
- [恢复及可用性结果](../datasets/evaluation/ct_independent_context_repair_report.json)
- [原定七策略重放](../datasets/evaluation/ct_independent_retrieval_report_v2.json)
- [冻结联合聚类重放](../datasets/evaluation/ct_independent_context_pattern_report_v2.json)
- [原有支持项一致性](../datasets/evaluation/ct_utility_repair_replay_parity.json)

保持demoparser2 0.41.3，依次执行`repair_ct_independent_utility.py`、`retrieve_ct_independent_context.py`、`transfer_ct_independent_context_patterns.py`。需要对应本地Demo及源制品；脚本拒绝覆盖已有输出。当前脚本使用v2协议和新目录；修复前v1脚本/协议在提交`3336003`，原输出目录保留。

本轮恢复耗时约22.4秒、进程峰值RAM约872 MiB。0.42.1仅用于隔离版本诊断，未替换冻结实验环境。

## 当前版本补充：v3

后续[原生状态调查](CT_UTILITY_EVENT_INVESTIGATION.md)解释了取消释放和死亡掉落。8对照3553个正常释放、830个CT查询计数匹配。烟雾死亡掉落反例不外推HE。保守v3将完整支持提升至245/246：R20在10秒已知，之后四时刻未知；原定检索与联合聚类已重放。上文60个恢复、226支持及828/830指v2历史阶段，不代表当前可用量。

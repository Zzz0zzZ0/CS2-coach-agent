# Coach 事实口径审核与修复

2026-09-07，审核身份：Codex / AI 辅助。审核现有 6 图、5 系列的 A/B 材料；未打开方法映射、未填写人工评分表，不能因此宣称独立盲审或真实教练评审。

## Verdict

事实口径修复通过。旧版存在可复现的分母和文案问题；新版本经过 148 项离线测试、历史 49 图 / 1,023 回合指标回归和全部 6 图材料重放。模型质量增益仍为 null。

## Findings

- **major / high：以胜局总数推荐弱侧。** 旧 Coach `side_transition` 建议“优先检查低胜局一侧”，但两侧回合数可能不同。case-01 的 MOUZ：CT 为 9/12（75.0%），T 为 4/5（80.0%），低胜局侧反而有更高样本胜率。case-06 同样出现 MOUZ CT 6/8（75.0%）、T 7/12（58.3%）。修复为显示每侧胜局、已知结果分母及阵容覆盖回合，按实际样本解释，取消低胜局即弱侧的推荐。
- **minor / high：同队受闪被写成队友受闪。** `team_flash_blinds_by_team` 只按投掷者和受闪者同队归类，包含自己受闪。六例分别有 38、44、40、76、70、30 个自己受闪事件；回合 / tick 与选手依据见报告。修复为“己方受闪（含自己）”，保留计数语义，并同步 Analyst、Coach、当前证据和模型输入说明。

## Verified

| 检查 | 结果 |
| --- | --- |
| 148 项测试 | 通过；覆盖不等长攻守、零胜局、未知结果、阵容缺失/冲突、模型输入字段及自己受闪 |
| 历史图谱 49 图、1,023 回合 | 原有指标无变化；完整阵容分母覆盖全部回合 |
| 原 6 图 Coach 材料 | 逐例原指标无变化，保留原 A/B 优先级并重渲染修正文案 |
| 2396950 两张此前已用地图 | 从本地 Demo 重解析以获得完整阵容，不从赢家数量推算分母 |
| 历史图谱、原评审包与两张空白人工表 | 保持原状，未登记团队知识库 |
| 本轮新增模型调用 | 0 |

新增 `side_performance_by_team` 只使用明确标为完整且双方阵营一致的回合阵容。字段包含 `rounds`、`known_outcomes`、`round_wins`、`win_rate_pct`；未知结果不计作失利，分母为零时胜率为 null。缺阵容时保留“分母不可用”，不补猜测百分比。完整阵容也支持无击杀事件回合的胜方归属，避免只依赖发出事件的选手。

审核汇总：[coach_ai_fact_audit_v1_report.json](../datasets/evaluation/coach_ai_fact_audit_v1_report.json)。修正后的 12 份 A/B 报告和共同证据留在本地 `data/evaluation/ai_review_v1/coach_fact_audit_v2/case-*.json`；它们复用旧选择，是事实修正重放，不是新增模型实验。

复现时使用冻结的旧代码工作树与已有本地数据：

```bash
git worktree add --detach /tmp/cs2-coach-frozen 6e3826e
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m scripts.audit_coach_facts \
  --baseline-root /tmp/cs2-coach-frozen \
  --output-dir data/evaluation/coach_fact_reproduction
.venv/bin/python -m pytest -q
```

审核脚本先核对旧 metrics 文件和历史图谱 SHA，再执行旧代码对照；运行时禁止网络连接，输出目录不可覆盖。

## Risks

本轮是开发助手对已有材料进行的事实审核。解析器与审核仍共享底层 Demo 事实，未独立看片。单场胜率没有消除经济、选边、地图和对手差异；只用于描述样本，不直接证明战术原因或训练收益。

原盲评包继续保存但已知有上述口径缺陷；后续人工质量比较应重新冻结双方共同的修正事实和报告，再收集评分，不能把旧评分混入新版或将事实修复归功于模型。

## Next actions

新比赛原始验收继续使用下载前冻结的 `6e3826e` 工作树。当前修复仅依据既有样本；待原始运行结束后，可以同样数据重放修正版并单列结果。实体别名与中英文检索基线随后在开发集处理，再冻结正式检索比较。

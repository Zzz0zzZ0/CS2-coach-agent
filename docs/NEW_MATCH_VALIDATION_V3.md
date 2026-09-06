# 两场新增比赛：首次失败、修复与回归

更新（2026-09-07）：历史图谱与 Milvus 已重建并切换至 1,019 个正式回合，语料和 AI 标签重新冻结，见 [v2 验收](HISTORICAL_DATA_REBUILD_V2.md)。下文原始数字和结果按其运行时版本保留；旧引用与旧实验必须配套旧数据库快照。

2026-09-07，AI 辅助审核。新增此前未入历史库的 G2–Aurora（2396944）与 G2–Natus Vincere（2396940），共 5 张地图。选择、日期窗口扩展及下载前冻结见 [AI 审核记录](AI_BENCHMARK_REVIEW.md)。仅下载这两个完整系列，未建立定时任务。

## 实际结果

| 阶段 | 版本与时点 | 地图通过 | 回合数 | 结论 |
| --- | --- | ---: | ---: | --- |
| 首次隔离运行 | 下载前冻结 `6e3826e` | 2/5 | 112 | 发现一张地图多算刀局，另两张仅因 NaVi 公共名称不同失败 |
| Coach 事实修复重放 | 首次解析前冻结 `381b1b1` | 2/5 | 112 | 攻守分母与受闪文案修复不能解决解析边界问题 |
| 解析与名称比较修复后 | 已观察这些数据后的回归 | 5/5 | 111 | 公开比分、完整阵容、引用验证及历史隔离全部通过 |

保留[首次失败报告](../datasets/evaluation/unseen_small_v3_baseline_report.json)、[Coach 修复重放](../datasets/evaluation/unseen_small_v3_coach_fix_report.json)和[最终回归报告](../datasets/evaluation/unseen_small_v3_postfix_report.json)，不覆盖、不改选比赛。三轮都没有远程模型调用。

| 比赛 | 地图 | 最终解析比分 | 回合 |
| --- | --- | --- | ---: |
| G2–Aurora | Anubis | G2 7 : 13 Aurora | 20 |
| G2–Aurora | Inferno | G2 19 : 16 Aurora | 35 |
| G2–Aurora | Mirage | G2 13 : 1 Aurora | 14 |
| G2–Natus Vincere | Ancient | G2 13 : 6 NaVi | 19 |
| G2–Natus Vincere | Inferno | G2 13 : 10 NaVi | 23 |

## 根因与最小修复

Mirage 在 tick 3777 有一个 T 获胜的赛前刀局；该段 8 次击杀全部使用刀。随后发生 warmup / begin_new_match，正式比赛首个 round_start 在 tick 5179，match-start 公告与 freeze end 在 tick 11722。旧解析器只筛选“round > 0 且胜方非空”，于是保留刀局并把真实比赛编号整体后移。

解析器现在使用最后一个有后续已完成回合的 match-start 公告及对应 round_start，确定当前比赛段。回合结尾、第一回合事件窗口和阵容快照共用该边界；不能只删除一个结果行，否则刀局击杀和赛前阵容仍会污染首回合。缺少这类开始事件的旧格式保留原路径；赛后无后续已完成回合的开始公告不会清空结果。规则不依赖比赛 ID、13 分或武器类型，也未据公开比分直接删回合。

Demo 使用 `NaVi`，HLTV 使用 `Natus Vincere`。仅在公开比分比较中显式声明该名称映射，保持 Demo 原计数不变；测试保证映射不能合并两支战队，也不能让错误比分通过。[修复后选择记录](../datasets/selections/unseen_small_v3_postfix_regression.json)明确标为事后回归。

150 项离线测试通过，包括重开前有真实胜方的回合、旧事件泄漏、阵容快照错位、赛后开始公告、公共名称映射与分数保持。真实新 Demo 再跑得到 111 回合。

## 历史数据影响

同一边界检查覆盖全部 49 个历史 Demo，发现 4 张地图各多包含一个赛前刀局，预计正式回合总数应从冻结库的 1,023 变为 1,019。逐文件边界与刀具证据见 [历史检查](../datasets/evaluation/historical_round_boundary_audit_v1.json)。

本轮历史图谱保持原 SHA，以保留初次实验可复现性；**线上历史数据尚未重建**。这些历史派生画像、相关性标签和指标需要在保留旧快照后重新生成。现有 AI 相关性分数只说明旧冻结解析事实上的表现，不能直接用于最终申请或求职材料。此前“旧指标未变”的 Coach 回归针对原解析事实，不能替代本次原始 Demo 边界核验。

下一项 P0 是备份并重建受影响历史数据、引用和派生索引，验证所有下游分母及图谱边，再重新冻结语料和 AI 标签。此后校准中英文检索基线；当前两场比赛已被观察，今后作回归，不重新称为未见测试。

## 制品与复现

[下载清单](../datasets/evaluation/unseen_small_v3_download_manifest.json)保留官方归档地址、字节数和 SHA-256；[制品清单](../datasets/evaluation/unseen_small_v3_artifact_manifest.json)记录三轮完整结果的哈希。RAR / Demo 和逐地图完整报告位于本地 `data/evaluation/unseen_small_v3/`，未提交大文件，也未写入历史图谱或向量库。保留 Downloads 原文件。

```bash
.venv/bin/python -m scripts.evaluate_unseen_match \
  --selection datasets/selections/unseen_small_v3_postfix_regression.json \
  --demo-dir data/evaluation/unseen_small_v3/demos \
  --graph-db data/evaluation/historical_rebuild_v2/graph_before.sqlite \
  --output data/evaluation/unseen_small_v3/reproduction/report.json
```

输出路径必须是新路径，历史库和代码必须与清单哈希一致。原版复现需要检出对应冻结版本，显式传入本地选择文件、Demo 和历史图谱的绝对路径。

这是小规模、真实输入的工程验收，两场同属一个赛事且均包含 G2。它证明发现的两类问题已在这些样本上修复，不证明检索泛化、教练建议价值或模型增益。

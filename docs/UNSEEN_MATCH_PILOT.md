# 首场独立比赛复盘验收

2026-09-06，使用历史图谱之外的完整 BO3 系列验证冻结实现：MOUZ 对 Vitality，HLTV 比赛 ID `2396950`。按指定日期窗口中最新的“已结束、有 Demo、ID 不在历史语料”比赛选取，下载前冻结清单和实现哈希。公开比赛页记录 Dust2 13–11、Mirage 13–7。[HLTV 原始比赛页](https://www.hltv.org/matches/2396950/mouz-vs-vitality-blast-open-porto-2026)

## 结果

| 地图 | 回合 | 完整名单 | 解析比分 MOUZ : Vitality | Verifier |
| --- | ---: | ---: | ---: | --- |
| Dust2 | 24 | 24/24 | 13 : 11 | pass |
| Mirage | 20 | 20/20 | 13 : 7 | pass |

两张地图全部检查通过，共 44 回合；解析比分与公开比分一致。每张地图均运行 `AnalysisPipeline` 到 Verifier，保留当前事实来源与历史检索来源；模型参数为 None，未连接 Milvus，执行期间禁止 Python socket 联网。

新比赛保存在 `data/evaluation/unseen_v1`，通过 match_id 与文件内容去重；同一系列两张地图全部隔离。运行前后历史图谱 SHA-256 相同，历史索引仍只有原来的 20 场比赛。Demo 日期来自浏览器显示日期，不推断时区。

## 可复现产物

- [下载前选择与隔离清单](../datasets/selections/unseen_match_pilot_v1.json)
- [压缩包与 Demo 校验和](../datasets/evaluation/unseen_download_v1.json)
- [首轮完整报告](../datasets/evaluation/unseen_pipeline_pilot_v1_report.json)
- [Dust2 复盘结果](../datasets/evaluation/unseen_pipeline_pilot_v1_report_2396950_Dust2.json)、[Mirage 复盘结果](../datasets/evaluation/unseen_pipeline_pilot_v1_report_2396950_Mirage.json)

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/python scripts/evaluate_unseen_match.py \
  --selection datasets/selections/unseen_match_pilot_v1.json \
  --demo-dir data/evaluation/unseen_v1/demos \
  --output data/evaluation/unseen_v1/reproduction-report.json
```

脚本拒绝空数据、重复系列、与历史比赛 ID 重叠、重复 Demo 内容、历史图谱或冻结实现变化；整场缺图或检查失败会返回非零退出码。输出文件不覆盖已有尝试。将来代码变化后应制定新版本清单并保留本次结果，不能伪装成继续使用未接触的测试样本。

## 结论边界

这是首场新比赛的工程复盘验收，支持解析与确定性报告链路能处理这场输入。它没有评估新语料的检索相关性，也没有专家评判建议的战术价值；单场样本无法估计跨比赛泛化能力。此后该系列已被观察，只能作回归或已知测试样本，后续盲测需选择新的完整系列。

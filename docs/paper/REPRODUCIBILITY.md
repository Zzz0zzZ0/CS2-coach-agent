# CT研究复现说明

区分数值重算、冻结前向、重新训练与原始观测重建。目前可独立运行的是主要技术结果的本地数值重算包；完整训练、原始Demo和人工材料尚未构成可公开下载的数据包。

## 已运行通过的数值重算

本地包为`output/tagnet/ct_confirmation_numerical_replay.zip`，约1.3MB，含124个校验条目和一个清单。内容包括108份冻结逐窗口损失/分量/表示数组、六图样本索引、原协议、主要结果、独立CPU脚本及依赖记录。不含模型权重、训练输入、Demo、人工回传、银标或凭据。

在解压目录执行：

```powershell
python -m pip install -r docs/paper/replay-requirements.txt
python scripts/replay_ct_confirmation.py --root . --output replay.json
```

已在独立解压目录以隔离Python模式实际运行，清单哈希通过。重算108份预测文件、216个系列×条件×种子记录，核对12系列的六条件均值、主要比值和两种区间，绝对容差1e-10。见[解压重算收据](../../datasets/evaluation/ct_confirmation_extracted_replay_report.json)与[构建及包SHA收据](../../datasets/evaluation/ct_confirmation_numerical_replay_report.json)。

此步骤从缓存损失开始，不重新计算解码器损失，不验证新模型推理、重训或战术相关性。独立统计实现另有与冻结评估器一致性的单测。

## 冻结前向与统计汇总

需要源特征`output/tagnet/ct_deployment_inputs_p1_v03`、源划分`output/tagnet/ct_grouped_confirmation_v7/folds.json`、108份源G4权重及源库`output/tagnet/ct_reconstruction_matrix/G4__*`、新队列输入核查`output/tagnet/ct_independent_inputs`。权重与输入哈希由`ct_independent_confirmation.json`及`ct_independent_analysis.json`指定。

在还原所需材料的新工作副本中执行；对应输出目录必须不存在，不删除当前冻结结果来腾空目录：

```powershell
& output/tagnet/.venv-gpu/Scripts/python.exe -X utf8 scripts/evaluate_ct_independent_confirmation.py
& E:/Anaconda/python.exe -X utf8 scripts/evaluate_ct_independent_confirmation.py --summarize
```

GPU环境负责冻结前向，参考CPU环境提供SciPy。实际版本见[环境收据](../../datasets/evaluation/ct_paper_environment.json)。上述解释器路径属于本机记录，其他机器需替换。跨硬件、驱动及数值库的新推理不承诺逐位一致；缓存损失的重算才使用1e-10比较。

## 从头训练与源拟合模式

完整开发入口`run_ct_reconstruction.py`接收`--protocol`、`--input-dir`、`--run-dir`、`--output-dir`。恢复源特征、划分后，以下为原布局的入口示例，不是本轮新增训练：

```powershell
python scripts/run_ct_reconstruction.py --protocol datasets/selections/ct_reconstruction_matrix.json --input-dir output/tagnet/ct_deployment_inputs_p1_v03 --run-dir output/tagnet/ct_grouped_confirmation_v7 --output-dir output/tagnet/ct_reconstruction_matrix
```

重训权重另存并记录新哈希，不能冒用原冻结权重身份。源模式、情境模式及迁移分别见`analyze_ct_deployment_patterns.py`、`analyze_ct_context_patterns.py`与`transfer_ct_independent_*`，参数和哈希以对应协议为准。

目前没有公开的下载后全链路训练验收。没有源特征或原权重时，应明确该层不可运行，不能用数值重算成功代替。

## 原始输入、情境版本和人工材料

原始采集采用冻结清单及预列替补；预算不构成任意补样许可。冻结输入解析用demoparser2 0.41.3，0.42.1仅作隔离诊断。情境v1支持166窗口，v2支持226，当前保守v3支持245且一窗口四个HE时刻未知；后续修正须保留旧输入与结果，重放原策略，不能在新查询上重拟合或挑权重。当前版本见[兼容说明](../CT_UTILITY_COMPATIBILITY.md)及唯一总计划。

`audit_ct_existing_judgments.py`和`evaluate_ct_existing_pool.py`需要原回传与精确刺激核对材料。原始回传未打包；人工和银标保持区分。公开受限候选池汇总不能实现逐评审审计。

## 公开、许可与匿名状态

软件许可证为MIT，这不自动赋予游戏录像、第三方资产或人工材料的再分发权。本地数值包尚待作者的权利与匿名核读，没有上传数据归档或匿名平台。

[期刊现行说明](https://transactions.games/submit/submission-guidelines)的2025年起双匿名通知优先于页面旧的单盲段落。当前工作库、许可证、来源URL和元数据没有完成匿名处理。作者需确认公开范围、原始材料访问条件及审稿去标识方式；当前包不称为可直接提交的匿名研究包。

## 工作稿PDF构建

本轮使用本地便携Tectonic0.17.0编译原IEEEtran源，未上传文稿到在线编译服务。由`main.tex`所在目录执行`tectonic --keep-logs --outdir <输出目录> main.tex`；保留相对图表/参考文献路径。软件来源及SHA、最终11页PDF和页面核查范围见`ct_manuscript_build_report.json`。PDF在本机`output/pdf/ct_cross_map_draft.pdf`，属于工作稿；数值包只复现聚合，不承担整份PDF构建。

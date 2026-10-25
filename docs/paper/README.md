# CT 论文工作区

当前英文主文是 [manuscript/main.tex](manuscript/main.tex)，文献库是 [references.bib](manuscript/references.bib)。研究顺序以[唯一研究总计划](../CT_PUBLICATION_ROADMAP.md)为准。主文按完整研究论文建立，不改为预测短稿。

使用方式：在主文里逐节填写，实验完成后替换对应 `Pending [ID]`，同时更新下表中的证据链接和状态。没有结果的格子不填0、不写成功结论；阶段完成必须有实际制品。摘要与最终贡献在主结果齐备后定稿。

后续直接编辑此主文，以Git保留修订历史。

## 本次核查

2026-10-25：9个正文主章节、2个附录章节已建立；17个待完成标记编号唯一。新增E1输入审计表和方法描述后，当前引用库为4篇；辅助表10个数字与v17结构化报告一致。此处是结构/数据一致性核查，不是全文或实验验收。

内置LaTeX首次编译返回 `Compilation timed out`，没有具体TeX错误诊断。源文件与文献库已保留，PDF编译和视觉排版尚未验收；本轮没有交付或声称生成了PDF。

## 章节与实验对应

| 章节 | 内容/问题 | 实验 | 当前状态与证据 |
| --- | --- | --- | --- |
| 摘要、引言 | 完整研究目标、缺口、贡献与主结果 | R1–R4 | 引言起草；摘要及最终贡献待主任务结果，`ABS/INTRO` |
| 相关工作 | TAGNet、集合/图表示、电竞部署与检索、跨域评测 | E0 | 初始3篇真实引用；完整对照待补，`RW` |
| 任务与数据 | 观测窗口、开发/独立数据、输入可见性 | E0/E5 | 开发9系列、22 Demo、6图、465窗口已写；独立队列待冻结，`DATA` |
| 共同表示 | 区域功能、高度/地面、关系与未知掩码 | E1 | 13维节点/3维成对输入接口和465回合导出已完成；新增方法与每图审计表已填。功能语义、资产与主表示验收仍保留`REP/NAV/RES1` |
| 模型与训练 | 完整输入非图、图、静态/学习时序、公平损失与选择 | E2 | 已有组件说明；主任务矩阵与目标待冻结，`TRAIN/RES2` |
| 评测协议 | 模式、同库检索、系列单位、主比较和统计 | E3–E5 | 定义待正式冻结，`METRIC/STAT`；不把旧试点协议冒称最终注册 |
| 主结果 | 表示有效性、模型贡献、模式及检索、新系列泛化 | E1–E5 | 均留明确结果槽位，`RES1/RES2/RES34/RES5` |
| 辅助预测结果 | 原共同特征的预测控制 | E6 | 已填v17主数值表；[结构化报告](../../datasets/evaluation/ct_information_control_v17_report.json) |
| 讨论与结论 | 解释、失败、适用条件和最终结论 | E1–E6 | 已写当前事实边界，主任务解释待补，`DISC/CONC` |
| 附录与声明 | 复现、样本、版本、人工/银标来源及事实性声明 | 全部 | `REPRO/DECL`；作者、同意、审批、资金等未知内容不自动补写 |

E0：原研究来源/数值复核；E1：共同表示与有效性；E2：主模型/输入/时序控制；E3：模式稳定性与解释；E4：公平检索与判断；E5：冻结后的独立新系列；E6：辅助状态预测。

这些ID只用于组织稿件，不代表新增实验已经注册或执行。E1–E5的准确指标、模型选择和预算仍按总计划依次确定。

## E1已完成的输入工程

[输入报告](../../datasets/evaluation/ct_deployment_input_report.json)与[纯计算接口](../../app/services/ct_deployment_service.py)定义一个几何输入候选，版本`ct-deployment-input-v0.1`。没有启用新的战术职责或训练新模型。

| 字段 | 定义 | 有效性 |
| --- | --- | --- |
| 节点0–7 | 原五粗区域、血量、装备变换、存活 | 原定义保留；死亡节点置零，粗类别不当作新职责真值 |
| 节点8–9 | 当前存活玩家内的相对高差，固定除512 | 仅依赖当前帧；不是地图楼层标签 |
| 节点10–12 | 腾空、落地、未知 | 物理状态未知时前两维无监督有效性，未知指示仍可观测 |
| 三个成对字段 | 欧氏距离/5000、水平距离/5000、绝对高差/512 | 只保留当前存活玩家对，排除对角线 |
| 功能职责 | 九类词汇单独保留为元数据 | 105个位置条目全未验收，所有存活观测均为unknown，不送入模型 |
| 原始位置名、NAV候选 | 用于溯源/诊断 | 单独导出，不送入模型；补丁相同也不证明资产完全兼容 |

当前导出465个窗口、11,368个存活观测；三项新契约检查通过。旧原始输入48项哈希在导出前后核对，样本顺序与v7一致；新NPZ可在禁用pickle下读取，死亡/无效成对值均为零。物理地面状态、NAV诊断总数与v17对齐。耗时约1.38秒，进程工作集峰值约104.04 MiB，无GPU训练。

本机数据保存在`output/tagnet/ct_deployment_inputs_p1/`，不随仓库分发。复跑需原本机数据，并指定不存在的新目录：

```powershell
& E:/Anaconda/python.exe scripts/audit_ct_deployment_features.py --run-dir output/tagnet/ct_grouped_confirmation_v7 --inventory datasets/evaluation/ct_map_semantics_v8_report.json --context-dir output/tagnet/ct_ground_navigation_v9_checked --role-review datasets/evaluation/ct_map_role_review_v9.json --output-dir output/tagnet/ct_deployment_inputs_p1_reproduce
```

P1仍未整体通过：当前实现解决字段接入和掩码，不能替代六图职责核实、具体部署解释或主任务效果评测。原粗分类的other占比按当前冻结队列实算为50.57%–81.01%，不是新模型错误率。

## 新增主张与证据记录

[source_manifest.json](source_manifest.json)登记来源、定位和哈希，[claims.csv](claims.csv)绑定主文新增E1/工作流主张的文本哈希。主文中的`E1`是实验号，`E101`等是来源号，两者不同。当前只覆盖本轮新增段落和表格，不冒称全稿审计。

工程核查状态是agent-checked，来源的人类核读状态全部保留unverified，未填写核读人或日期。机器可检查结构和数字一致性，不据此声称人工核实或投稿就绪。科学写作skill的本地通用审计针对Markdown；当前TeX仅做相应的来源/哈希绑定核查，不冒称已通过该审计器的全稿认证。

## 现有证据入口

- [v7数据与系列隔离](../CT_GENERALIZATION_CONFIRMATION_V7.md)
- [原TAGNet来源](../TAGNET_PROVENANCE.md)及[数值/GPU复核](../TAGNET_NUMERICAL_DIAGNOSIS.md)
- [v17实际实施结果](../CT_IMPLEMENTATION_V17.md)及[几何核查报告](../../datasets/evaluation/ct_geometry_features_v17_report.json)
- [辅助预测证据补充](CT_CROSS_MAP_EVIDENCE_DRAFT.md)：保留v7/v14/v17的完整历史方法、表格和限制；它不再作为另一份并行主稿
- [人工回收记录](../CT_HUMAN_RETURNS_V12.md)：保留原始来源、版本及缺失分类，不在本轮重发旧题

主文的v17辅助表取自结构化报告，按种子误差平均与等系列汇总口径显示。新主任务结果必须填入E1–E5自己的位置，不能用这张表替代。

## 图表预留

研究流程与隔离图、六图表示/失配示例、输入与模型对照、模式/检索证据、新系列主结果分别对应E0/E1/E2/E3–E4/E5。现有辅助预测图保留在[历史矢量图](../assets/ct_information_control_v17.svg)。先有数据和图意再作图，不生成虚构结果。

## 已检索的 skill：高星原仓库优先

2026-10-25通过GitHub仓库API核对。下列星标属于整个仓库，不代表某个skill的独立评分；四库均未归档，仓库许可证均显示MIT。K-Dense已精简为8个论文/实验相关skill，固定上游版本`593377bb048752abb0152deab9fbb1083a6087df`；其余169个已移到技能目录外的本机备份，可按需恢复。保留：scientific-writing、literature-review、citation-management、experimental-design、statistical-analysis、statistical-power、scientific-visualization、scientific-critical-thinking。其他候选库未安装。配套科学软件/API依赖未安装，实际功能兼容性尚未测试。

| 优先来源 | 仓库星标快照 | 最近push（UTC日期） | 与本研究的用途 |
| --- | ---: | --- | --- |
| [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 54,407 | 2026-10-19 | 研究设计、批判性检查、统计与写作规范；仅选相关skill，不整包引入其他领域工具 |
| [Orchestra-Research/AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs) | 13,906 | 2026-10-11 | ML论文组织、对照、消融和引用流程；会议格式不直接套到ToG |
| [Master-cai/Research-Paper-Writing-Skills](https://github.com/Master-cai/Research-Paper-Writing-Skills) | 7,766 | 2026-06-23 | 正文章节、段落论证、主张与证据对应、自审；已完整阅读主SKILL.md |
| [zLanqing/codex-claude-academic-skills](https://github.com/zLanqing/codex-claude-academic-skills) | 5,254 | 2026-05-14 | 中文科研讨论、写作检查与科学计算辅助；英文主稿语言按本项目已定要求 |

具体入口：

- 写作主力候选：[Master-cai research-paper-writing](https://github.com/Master-cai/Research-Paper-Writing-Skills/blob/main/research-paper-writing/SKILL.md)。按章节阅读对应参考，不改变已定研究主线。
- ML论文与实验叙事候选：[Orchestra ml-paper-writing](https://github.com/Orchestra-Research/AI-Research-SKILLs/blob/main/20-ml-paper-writing/ml-paper-writing/SKILL.md)。
- 实验设计与证据候选：[K-Dense scientific-critical-thinking](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-critical-thinking/SKILL.md)。
- 统计候选：[K-Dense statistical-analysis](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/statistical-analysis/SKILL.md)。系列/查询嵌套不能直接套独立样本检验。
- 写作规范参考：[K-Dense scientific-writing](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/scientific-writing/SKILL.md)。
- 中文写作候选：[zLanqing research-writing-skill](https://github.com/zLanqing/codex-claude-academic-skills/blob/main/research-writing-skill/SKILL.md)。

历史说明：最初框架参考的是[StickTaTa的Codex适配版](https://github.com/StickTaTa/codex-scientific-writing-skill/blob/main/scientific-writing/SKILL.md)，同日核对仅3星；保留其实际来源记录，后续不再列为优先候选。框架与证据数据不因更换写作参考而改动。此前还核对了K-Dense写作器（2,520星）与Google DeepMind science-skills（3,327星）；前者与K-Dense库用途重叠，后者主要面向生命科学数据库，本项目不优先采用。

## 初始文献来源

- TAGNet：[作者CITATION.cff](https://github.com/weyoung-open-lab/TAGNet-CS2/blob/main/CITATION.cff)提供作者、题目、2026年、期刊与DOI。未独立核读出版页元数据，不猜卷期页码。
- Deep Sets：[官方论文页](https://papers.nips.cc/paper/2017/hash/f22e4747da1aa27e363d86d40ff442fe-Abstract.html)及其BibTeX导出。文献库作者字段依官方导出。
- Janossy Pooling：[arXiv原始记录](https://arxiv.org/abs/1811.01900)列出作者、题目及ICLR 2019会议引用。
- Scientific Agent Skills：[当前arXiv原始记录](https://arxiv.org/abs/2609.00065)核对作者、年份、题目和DOI；已按该skill要求加入工作流软件说明及参考文献，不将其当作模型有效性的证据。

这是初始引用库，尚未完成相关工作系统核查。没有编造引用或加入无法解析的占位citation key。

# CT 论文工作区

当前英文主文是 [manuscript/main.tex](manuscript/main.tex)，文献库是 [references.bib](manuscript/references.bib)。研究顺序以[唯一研究总计划](../CT_PUBLICATION_ROADMAP.md)为准。主文按完整研究论文建立，不改为预测短稿。

使用方式：在主文里逐节填写，实验完成后替换对应 `Pending [ID]`，同时更新下表中的证据链接和状态。没有结果的格子不填0、不写成功结论；阶段完成必须有实际制品。摘要与最终贡献在主结果齐备后定稿。

后续直接编辑此主文，以Git保留修订历史。

## 本次核查

2026-10-25：9个正文主章节、2个附录章节已建立；17个待完成标记编号唯一；3个引用key有对应文献项；辅助表10个数字与v17结构化报告一致；写作指南与总计划内27个本地链接存在。此处是结构/数据一致性核查，不是全文或实验验收。

内置LaTeX首次编译返回 `Compilation timed out`，没有具体TeX错误诊断。源文件与文献库已保留，PDF编译和视觉排版尚未验收；本轮没有交付或声称生成了PDF。

## 章节与实验对应

| 章节 | 内容/问题 | 实验 | 当前状态与证据 |
| --- | --- | --- | --- |
| 摘要、引言 | 完整研究目标、缺口、贡献与主结果 | R1–R4 | 引言起草；摘要及最终贡献待主任务结果，`ABS/INTRO` |
| 相关工作 | TAGNet、集合/图表示、电竞部署与检索、跨域评测 | E0 | 初始3篇真实引用；完整对照待补，`RW` |
| 任务与数据 | 观测窗口、开发/独立数据、输入可见性 | E0/E5 | 开发9系列、22 Demo、6图、465窗口已写；独立队列待冻结，`DATA` |
| 共同表示 | 区域功能、高度/地面、关系与未知掩码 | E1 | 原共同输入已写；新语义和资产有效性待验收，`REP/NAV/RES1` |
| 模型与训练 | 完整输入非图、图、静态/学习时序、公平损失与选择 | E2 | 已有组件说明；主任务矩阵与目标待冻结，`TRAIN/RES2` |
| 评测协议 | 模式、同库检索、系列单位、主比较和统计 | E3–E5 | 定义待正式冻结，`METRIC/STAT`；不把旧试点协议冒称最终注册 |
| 主结果 | 表示有效性、模型贡献、模式及检索、新系列泛化 | E1–E5 | 均留明确结果槽位，`RES1/RES2/RES34/RES5` |
| 辅助预测结果 | 原共同特征的预测控制 | E6 | 已填v17主数值表；[结构化报告](../../datasets/evaluation/ct_information_control_v17_report.json) |
| 讨论与结论 | 解释、失败、适用条件和最终结论 | E1–E6 | 已写当前事实边界，主任务解释待补，`DISC/CONC` |
| 附录与声明 | 复现、样本、版本、人工/银标来源及事实性声明 | 全部 | `REPRO/DECL`；作者、同意、审批、资金等未知内容不自动补写 |

E0：原研究来源/数值复核；E1：共同表示与有效性；E2：主模型/输入/时序控制；E3：模式稳定性与解释；E4：公平检索与判断；E5：冻结后的独立新系列；E6：辅助状态预测。

这些ID只用于组织稿件，不代表新增实验已经注册或执行。E1–E5的准确指标、模型选择和预算仍按总计划依次确定。

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

2026-10-25通过GitHub仓库API核对。下列星标属于整个仓库，不代表某个skill的独立评分；四库均未归档，仓库许可证均显示MIT。K-Dense库的177个skill已安装到Codex用户技能目录，固定上游版本`593377bb048752abb0152deab9fbb1083a6087df`，技能文件及配套资源约20.3 MiB；其余候选尚未安装。已核对177份技能说明，配套科学软件/API依赖未安装，实际功能兼容性尚未测试。

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

这是初始引用库，尚未完成相关工作系统核查。没有编造引用或加入无法解析的占位citation key。

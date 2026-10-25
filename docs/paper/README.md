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
| 相关工作 | TAGNet、集合/图表示、电竞部署与检索、跨域评测 | E0 | [针对性来源核对](related_work.md)已补团队视频表征、移动模仿与地图距离；跨域检索/稳定性和TAGNet出版全文仍待补，`RW` |
| 任务与数据 | 观测窗口、开发/独立数据、输入可见性 | E0/E5 | 开发9系列、22 Demo、6图、465窗口已写；独立队列待冻结，`DATA` |
| 共同表示 | 观测状态、空间结构、高度/地面和时间有效性 | E1 | 15维节点/3维成对输入接口和465回合导出已完成，含相邻采样位移速率；职责解释针对具体部署语境。额外结构字段与主任务效果待验收，保留`REP/NAV/RES1` |
| 模型与训练 | 完整输入非图、图、静态/学习时序、公平损失与选择 | E2 | 六条件和共同重建已实现；轨迹修正后源侧试跑完成，[开发矩阵](../../datasets/selections/ct_reconstruction_matrix.json)已冻结并运行，`RES2`待完成 |
| 评测协议 | 模式、同库检索、系列单位、主比较和统计 | E3–E5 | 定义待正式冻结，`METRIC/STAT`；不把旧试点协议冒称最终注册 |
| 主结果 | 表示有效性、模型贡献、模式及检索、新系列泛化 | E1–E5 | 均留明确结果槽位，`RES1/RES2/RES34/RES5` |
| 辅助预测结果 | 原共同特征的预测控制 | E6 | 已填v17主数值表；[结构化报告](../../datasets/evaluation/ct_information_control_v17_report.json) |
| 讨论与结论 | 解释、失败、适用条件和最终结论 | E1–E6 | 已写当前事实边界，主任务解释待补，`DISC/CONC` |
| 附录与声明 | 复现、样本、版本、人工/银标来源及事实性声明 | 全部 | `REPRO/DECL`；作者、同意、审批、资金等未知内容不自动补写 |

E0：原研究来源/数值复核；E1：共同表示与有效性；E2：主模型/输入/时序控制；E3：模式稳定性与解释；E4：公平检索与判断；E5：冻结后的独立新系列；E6：辅助状态预测。

这些ID只用于组织稿件，不代表新增实验已经注册或执行。E1–E5的准确指标、模型选择和预算仍按总计划依次确定。

## E1已完成的输入工程

[当前输入报告](../../datasets/evaluation/ct_deployment_input_v03_report.json)与[纯计算接口](../../app/services/ct_deployment_service.py)定义一个几何/采样运动输入候选，版本`ct-deployment-input-v0.3`。位置与地图结构是观测/环境信息，不预先指定玩家职责。E1导出与下节E2模型训练分别记录。

| 字段 | 定义 | 有效性 |
| --- | --- | --- |
| 节点0–7 | 原五粗区域、血量、装备变换、存活 | 原定义保留；死亡节点置零，粗类别不当作新职责真值 |
| 节点8–9 | 当前存活玩家内的相对高差，固定除512 | 仅依赖当前帧；不是地图楼层标签 |
| 节点10–12 | 腾空、落地、未知 | 物理状态未知时前两维无监督有效性，未知指示仍可观测 |
| 节点13–14 | 相邻采样的水平位移模长/间隔、带符号垂直位移/间隔，再固定除250 | 按玩家身份对齐，当前及前一采样都存活才有效；首帧/无效区间置零且掩码为假，静止为有效零值。250是固定尺度，不是速度上限，不裁剪 |
| 三个成对字段 | 欧氏距离/5000、水平距离/5000、绝对高差/512 | 只保留当前存活玩家对，排除对角线 |
| 战术职责 | 无固定位置到职责词表，也不导出职责占位数组 | 解释针对具体部署片段与时刻；允许多种解释或证据不足 |
| 原始位置名、NAV候选 | 用于溯源/诊断 | 单独导出，不送入模型；补丁相同也不证明资产完全兼容 |

当前导出465个窗口、11,368个存活观测；五项契约检查通过，包括同地点资源/队友变化、整队移动与静止、逐帧玩家重排、水平旋转及非等间隔采样。48项旧原始输入哈希在导出前后核对，样本顺序与v7一致。与v0.2共有的8个数组逐项比较：节点及字段掩码的前13维、其余全部数组逐元素完全一致。这些是输入检查，不是模型效果结论。

9,049个存活观测具有有效前一帧；2,319个存活观测的运动信息未知，全部保留。其中8,679个有效区间水平位移非零。首帧不读取窗口开始前的坐标；不利用未来帧填充。导出耗时1.15秒，进程峰值内存103.60 MiB，未使用GPU。

本机当前数据在`output/tagnet/ct_deployment_inputs_p1_v03/`，不随仓库分发。复跑需原本机数据，并指定不存在的新目录：

```powershell
& E:/Anaconda/python.exe scripts/audit_ct_deployment_features.py --run-dir output/tagnet/ct_grouped_confirmation_v7 --inventory datasets/evaluation/ct_map_semantics_v8_report.json --context-dir output/tagnet/ct_ground_navigation_v9_checked --output-dir output/tagnet/ct_deployment_inputs_p1_v03_reproduce
```

观测输入契约已经过计算核查，可继续定义主任务基线；主任务有效性仍待实验。原粗分类的other占比为50.57%–81.01%，反映地理类别的汇总程度，不是职责不明确的比例或模型错误率。额外NAV/结构属性仍要各自验证，不能据此指定玩家职责。

### 情境信息的实际可用范围

| 信息 | 当前状态 |
| --- | --- |
| 五时刻的位置、存活、血量与装备 | 已接入；原始位置名用于溯源 |
| 队友相对几何与高差 | 已接入，可区分同一位置下的不同资源/阵型观测 |
| 移动与阵型变化 | v0.3补入相邻采样位移速率，保留相对几何序列；可区分原13/3摘要遗漏的一类整队移动，不代表完整路径/水平朝向 |
| 道具事件、朝向/可见信息、比分及回合经济 | 未接入当前接口；能否可靠取得、信息可见性和对齐需逐项核对 |
| 意图、沟通与真正承担的职责 | 当前未观测；不能从地点直接当作真值 |

评测针对具体部署片段，不要求每个地图位置拥有固定核心功能。同一地点可对应不同职责，同一职责也可通过不同位置和协同方式实现；只解释给定信息支持的部分，不使用未来胜负补充输入。

合成诊断保持粗类别、资源和队形关系不变，让全队每帧共同平移：v0.2的13维节点/3维成对摘要仍完全相同；v0.3新增运动字段可以区分。它检验信息是否保留，不是模型效果或战术意图证据。当前只表示相邻采样端点位移，区间内绕路、出发后返回原点、水平移动方向仍可能无法区分；水平旋转/反射下不变。道具、可见信息和局势项仍未接入。

历史：[v0.1报告](../../datasets/evaluation/ct_deployment_input_report.json)、[v0.2报告](../../datasets/evaluation/ct_deployment_input_v02_report.json)及对应本机导出保留。旧接口分别对应Git提交`5e430fc`、`62b3803`。九类职责占位与105地点审核门槛已撤回，旧产物不代表当前设计。历史原始数据及人工评分未修改。

## E2主任务实现与训练

[训练入口](../../scripts/run_ct_reconstruction.py)实现六个神经条件、同一64维窗口瓶颈、同一525字段解码器，以及七类等权重建损失。节点和边端点的同一次玩家匹配贯穿五时刻。所有条件重建相同的v0.3目标，输入消融不删减考核字段；不使用职责标签或未来胜负。

第一版在逐帧汇总后接GRU，[旧工程试跑](../../datasets/evaluation/ct_reconstruction_pilot_report.json)及源码提交`83168e8`保留。随后用合成样例确认这种结构会忽略跨帧身份对应关系；修正为图编码后逐玩家轨迹GRU、非图编码后逐整窗联合排列GRU，最后再平均。[当前源侧试跑](../../datasets/evaluation/ct_reconstruction_tracks_pilot_report.json)六条件全部完成，105.73秒，PyTorch显存分配峰值128.39 MiB，进程内存峰值1562.08 MiB；没有计算测试结果或选取“最佳架构”。两批试跑都不计入正式开发矩阵。

[六项重建契约检查](../../test_ct_reconstruction.py)通过，包含整窗匹配、成对端点、死亡/未知掩码、六条件梯度、全局重排不变、局部换轨可区分、因果前缀及输入消融。[四项分析检查](../../test_ct_reconstruction_analysis.py)也已通过，验证直接参照的轨迹匹配、未知与真实零值的区别、等系列汇总及证据图死亡坐标处理；这些是代码检查，不是模型独立泛化验收。

[开发矩阵协议](../../datasets/selections/ct_reconstruction_matrix.json)在输出矩阵测试成绩前固定：15折×6条件×3种子=270份权重，100轮、批量16、验证重建选轮次，配方与源哈希见协议；不复用试跑或v17预测权重。按源侧试跑估算约65分钟，时间保护上限2小时，输出预计220 MiB、规划上限512 MiB（并非磁盘配额机制）；单训练进程，启动需2 GiB可用内存，运行低于1.5 GiB即保存已有进度停止。矩阵现处运行中，完整性和结果由完成收据决定。

```powershell
& output/tagnet/.venv-gpu/Scripts/python.exe test_ct_reconstruction.py -v
& output/tagnet/.venv-gpu/Scripts/python.exe scripts/run_ct_reconstruction.py --protocol datasets/selections/ct_reconstruction_matrix.json --input-dir output/tagnet/ct_deployment_inputs_p1_v03 --run-dir output/tagnet/ct_grouped_confirmation_v7 --output-dir output/tagnet/ct_reconstruction_matrix_reproduce
```

[汇总与检索导出](../../scripts/evaluate_ct_reconstruction.py)只接受全部矩阵条件完成的报告；核对权重、所选轮次、样本顺序、各条件/种子覆盖后，先在每窗口平均种子，再在系列内平均、最后等系列汇总。描述性区间以系列重采样，不能消除共享队伍和重叠训练折的依赖。

直接参照规则已写入同一协议：24字段统计序列只用源训练集拟合标准化；完整观测直接匹配枚举一致整窗玩家重排。神经表示用64维均方距离。各方法使用相同源训练候选库，分别列出同图跨系列与跨地图结果。新导出的排名没有相关性判断，不计算战术nDCG/Recall，也不自动套用旧题的人工分数。

图/非图参数量分别登记，未完全匹配；时序条件还包含轨迹对应关系的保留，不将其优势全归因于单一模块。原始回归输出不保证路径可通行或几何完全可实现。主文结果槽位等待实际完整结果，独立P4–P5仍未开始。

### E3–E4分析与图表准备

[模式协议](../../datasets/selections/ct_deployment_pattern_analysis.json)于矩阵运行期间、查看测试成绩和执行真实数据聚类前记录，不冒称预注册独立研究。[实现](../../scripts/analyze_ct_deployment_patterns.py)只用源训练集选择K=2–6并拟合质心；另报源地图/系列关联、三种子共同有效查询上的ARI及缺失原因。种子0的各条件另做20次源系列重采样，固定神经编码器和K，不能当作全流程不确定性。[两项合成检查](../../test_ct_deployment_patterns.py)通过，验证查询不能改变源选K/质心及退化情况显式报告。

当前只准备未命名模式和未评分候选；95%源距离范围与最小簇支持是诊断规则，不是战术相关性或校准置信度。[绘图入口](../../scripts/plot_ct_reconstruction.py)保留逐系列数据和共同尺度、输出PDF/SVG/PNG及数据表。[观测证据入口](../../scripts/export_ct_deployment_evidence.py)每图固定取第一条G4查询，展示图/非图时序模型种子0的首位跨地图候选，不按效果挑选。轨迹虚线只连采样端点，不画成实际通行路线；尚无真实数据出图或视觉验收记录。

### 投稿格式核对（2026-10-25）

按[ToG官方指南](https://transactions.games/submit/submission-guidelines)继续准备Full paper。页面顶部列10–14页、超过10页收费，旧正文另有超过12页需说明的表述；最终页数与投稿包需再次核对，不据此缩减研究问题。2025年起的置顶通知要求双匿名，覆盖正文、致谢及供审查的代码/数据入口；同页旧版单盲表述与之不一致，不能直接沿用。当前公开开发仓库不是匿名投稿包，本轮不执行外部提交。

[IEEE图形指南](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/)要求用形状/线型等辅助颜色。当前图按180 mm左右双栏宽度作可编辑矢量草图；正式格式、字体与实际尺寸需出图后核验，不能凭DPI或调色板自称投稿合规。

## 新增主张与证据记录

[source_manifest.json](source_manifest.json)登记来源、定位和哈希，[claims.csv](claims.csv)绑定已登记的E1/E2、开发模式方法、相关工作和工作流段落的文本哈希。主文中的`E1`是实验号，`E101`等是来源号，两者不同。当前只覆盖已登记段落和表格，不冒称全稿审计。

CSV的`evidence_ids`按写作工具接口使用分号分隔，TeX中的来源标记仍使用逗号。登记格式和来源ID关联已通过工具解析；人类尚未核读的错误状态原样保留，不通过把状态改成`verified`来消除。

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

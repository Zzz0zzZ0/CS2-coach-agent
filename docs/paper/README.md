# CT 论文工作区

当前英文主文是 [manuscript/main.tex](manuscript/main.tex)，文献库是 [references.bib](manuscript/references.bib)。研究顺序以[唯一研究总计划](../CT_PUBLICATION_ROADMAP.md)为准。主文按完整研究论文建立，不改为预测短稿。

使用方式：在主文里逐节填写，实验完成后替换对应 `Pending [ID]`，同时更新下表中的证据链接和状态。没有结果的格子不填0、不写成功结论；阶段完成必须有实际制品。摘要与最终贡献在主结果齐备后定稿。

后续直接编辑此主文，以Git保留修订历史。

## 本次核查

2026-10-26：现有英文摘要按170词填写；当前13篇参考文献、107个绑定主张、62条来源，2个待完成标记（复现发布与作者声明）。新系列技术确认已经完成：12系列、246窗口、108份冻结源权重；图/非图主要损失比1.01576，95%条件区间包含持平。所有来源仍待作者核读，不把自动核查当成人类验收。

此前整篇LaTeX编译返回 `Compilation timed out`；本轮更新后的主文已通过内置编译器。两张结果图、六张固定查询观测图的PDF/SVG/PNG均已逐图检查。本轮已导出11页工作稿，渲染全页总览并放大核查第1/4/9/11页；修正两处表格溢出，最终无Overfull警告、字体全部嵌入且无Type3。视觉核查与人类作者核读、投稿核验分开。

## 章节与实验对应

| 章节 | 内容/问题 | 实验 | 当前状态与证据 |
| --- | --- | --- | --- |
| 摘要、引言 | 完整研究目标、缺口、贡献与主结果 | R1–R4 | 完整引言/贡献及R1–R4已按现有结果填写；不将分支分开写成统计解耦 |
| 相关工作 | TAGNet、集合/图表示、电竞部署与检索、跨域评测 | E0 | 13篇定向文献已进入正文，包含团队表征、移动、地图距离、域迁移、聚类稳定性及不完整检索判断；来源定稿阅读与负责的人类核读保持区分 |
| 任务与数据 | 观测窗口、开发/独立数据、输入可见性 | E0/E5 | 数据表已填开发9系列/465窗口与新12系列/246窗口；含阵亡窗口74/41；语义端点仍未验收 |
| 共同表示 | 观测状态、空间结构、高度/地面和时间有效性 | E1 | 15维节点/3维成对输入接口和465回合导出已完成，含相邻采样位移速率；职责解释针对具体部署语境。额外结构字段与主任务效果待验收，保留`REP/NAV/RES1` |
| 模型与训练 | 完整输入非图、图、静态/学习时序、公平损失与选择 | E2 | 六条件和共同重建已实现；轨迹修正后源侧试跑完成，[开发矩阵](../../datasets/selections/ct_reconstruction_matrix.json)已完成270条件并核查，结果已填主文 |
| 评测协议 | 模式、同库检索、系列单位、主比较和统计 | E3–E5 | 源侧拟合、归一化与区间公式已写；本地冻结和事后修正分别披露，不称外部预注册 |
| 主结果 | 表示有效性、模型贡献、模式及检索、新系列泛化 | E1–E5 | E1–E5计算结果、固定策略迁移和保守v3已填；仅独立语义相关性仍未验收 |
| 辅助预测结果 | 原共同特征的预测控制 | E6 | 已填v17主数值表；[结构化报告](../../datasets/evaluation/ct_information_control_v17_report.json) |
| 讨论与结论 | 解释、失败、适用条件和最终结论 | E1–E6 | 已按R1–R4给出解释，补选择、容量、信息重叠和语义限制 |
| 附录与声明 | 复现、样本、版本、人工/银标来源及事实性声明 | 全部 | 本地独立数值包及分级复现说明已完成；公开权利、匿名及作者声明仍待核读，`REPRO/DECL` |

E0：原研究来源/数值复核；E1：共同表示与有效性；E2：主模型/输入/时序控制；E3：模式稳定性与解释；E4：公平检索与判断；E5：冻结后的独立新系列；E6：辅助状态预测。

实验ID本身不证明注册或执行。E2和E3的开发实现、规则及完成报告已链接；E5已完成新系列技术确认和固定迁移；E4独立语义相关性仍未确认，开发报告不能替代。

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

[开发矩阵协议](../../datasets/selections/ct_reconstruction_matrix.json)在输出矩阵测试成绩前固定：15折×6条件×3种子=270份权重，100轮、批量16、验证重建选轮次，配方与源哈希见协议；不复用试跑或v17预测权重。按源侧试跑估算约65分钟，时间保护上限2小时，输出预计220 MiB、规划上限512 MiB（并非磁盘配额机制）；单训练进程，启动需2 GiB可用内存，运行低于1.5 GiB即保存已有进度停止。矩阵已完成270/270条件，实际4158.93秒（69.32分钟），进程峰值内存1578.86 MiB，PyTorch显存分配峰值128.39 MiB；完整[开发报告](../../datasets/evaluation/ct_reconstruction_development_report.json)记录所有条件、轮次和权重哈希。

```powershell
& output/tagnet/.venv-gpu/Scripts/python.exe test_ct_reconstruction.py -v
& output/tagnet/.venv-gpu/Scripts/python.exe scripts/run_ct_reconstruction.py --protocol datasets/selections/ct_reconstruction_matrix.json --input-dir output/tagnet/ct_deployment_inputs_p1_v03 --run-dir output/tagnet/ct_grouped_confirmation_v7 --output-dir output/tagnet/ct_reconstruction_matrix_reproduce
```

[汇总与检索导出](../../scripts/evaluate_ct_reconstruction.py)只接受全部矩阵条件完成的报告；核对权重、所选轮次、样本顺序、各条件/种子覆盖后，先在每窗口平均种子，再在系列内平均、最后等系列汇总。描述性区间以系列重采样，不能消除共享队伍和重叠训练折的依赖。

直接参照规则已写入同一协议：24字段统计序列只用源训练集拟合标准化；完整观测直接匹配枚举一致整窗玩家重排。神经表示用64维均方距离。各方法使用相同源训练候选库，分别列出同图跨系列与跨地图结果。新导出的排名没有相关性判断，不计算战术nDCG/Recall，也不自动套用旧题的人工分数。

图/非图参数量分别登记，未完全匹配；时序条件还包含轨迹对应关系的保留，不将其优势全归因于单一模块。原始回归输出不保证路径可通行或几何完全可实现。主文已填写完整开发结果；独立P4–P5仍未开始。

### E3–E4分析与图表准备

[模式协议](../../datasets/selections/ct_deployment_pattern_analysis.json)于矩阵运行期间、查看测试成绩和执行真实数据聚类前记录，不冒称预注册独立研究。[实现](../../scripts/analyze_ct_deployment_patterns.py)只用源训练集选择K=2–6并拟合质心；另报源地图/系列关联、三种子共同有效查询上的ARI及缺失原因。种子0的各条件另做20次源系列重采样，固定神经编码器和K，不能当作全流程不确定性。[两项合成检查](../../test_ct_deployment_patterns.py)通过，验证查询不能改变源选K/质心及退化情况显式报告。

当前只准备未命名模式和未评分候选；95%源距离范围与最小簇支持是诊断规则，不是战术相关性或校准置信度。[绘图入口](../../scripts/plot_ct_reconstruction.py)保留逐系列数据和共同尺度、输出PDF/SVG/PNG及数据表。[观测证据入口](../../scripts/export_ct_deployment_evidence.py)每图固定取第一条G4查询，展示图/非图时序模型种子0的首位跨地图候选，不按效果挑选。轨迹虚线只连采样端点，不画成实际通行路线；已对六个固定查询及两张结果图逐图检查；[图表与数据表](manuscript/figures/)保持来源哈希。局部重叠点的玩家编号可能重合，未移动原始观测点来美化图片。


### 已完成的开发结果

| 条件 | G3等系列重建目标 | G4等系列重建目标 |
| --- | ---: | ---: |
| 非图静态 | 0.104151 | 0.130487 |
| 非图时序 | 0.091641 | 0.123633 |
| 图静态 | 0.101017 | 0.130968 |
| 图时序 | 0.092370 | 0.125391 |
| 图时序，无运动输入 | 0.096085 | 0.126011 |
| 图时序，原共同输入 | 0.096766 | 0.125923 |

这里的目标混合七组CE/MSE，不称作战术准确率。两种时序条件优于各自静态条件；图时序比完整非图时序的损失反而高0.79%/1.42%，对应描述性配对区间均跨零，没有稳定图优势。新增运动在图时序条件下的G3收益3.87%，G4仅0.49%，后者区间[-0.68%,1.60%]，不能宣称稳定跨图收益。共享队伍与训练折仍限制区间解释。

[模式报告](../../datasets/evaluation/ct_deployment_pattern_report.json)完成270个源拟合分析。图时序G3的27次拟合有24次选择K=2，不强求六类。图时序G4的共同有效查询ARI均值0.406、诊断覆盖92.97%，非图时序为0.520、86.02%；不同K及共同有效查询子集限制直接比较。覆盖按1,395个查询×种子记录计，不能当作独立样本。更低重建损失没有保证模式更稳定，也没有验证真实职责。

已导出18,600条查询—方法—种子排名记录，底层仍是每种G3/G4条件各465个窗口。排名未评分；[六图固定观测证据](manuscript/figures/evidence.json)没有新增人工或AI相关性标注。现有人工/银标记录原样保留，不给新候选套用旧分数。

此前CI因聚类测试缺少开发依赖而失败，已补入锁定的scikit-learn及其测试依赖，并将绘图库移入出图入口。该修复当时本地全套460通过、7跳过；6项PyTorch研究契约另在研究环境通过。修复提交`245b2b6`的[离线测试与前端构建](https://github.com/Zzz0zzZ0/CS2-coach-agent/actions/runs/40182235158)已恢复通过。加入情境和受限旧候选池检查后，当前本地全套468通过、7跳过；新增的源侧推理小试还检查了冻结编码结果的一致性。

### 投稿格式核对（2026-10-25）

按[ToG官方指南](https://transactions.games/submit/submission-guidelines)继续准备Full paper。页面顶部列10–14页、超过10页收费，旧正文另有超过12页需说明的表述；最终页数与投稿包需再次核对，不据此缩减研究问题。2025年起的置顶通知要求双匿名，覆盖正文、致谢及供审查的代码/数据入口；同页旧版单盲表述与之不一致，不能直接沿用。当前公开开发仓库不是匿名投稿包，本轮不执行外部提交。

[IEEE图形指南](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/)要求用形状/线型等辅助颜色。当前图按180 mm左右双栏宽度作可编辑矢量草图；正式格式、字体与实际尺寸需出图后核验，不能凭DPI或调色板自称投稿合规。

## 新增主张与证据记录

[source_manifest.json](source_manifest.json)登记来源、定位和哈希，[claims.csv](claims.csv)绑定已登记的E1/E2、开发模式方法、相关工作和工作流段落的文本哈希。主文中的`E1`是实验号，`E101`等是来源号，两者不同。当前只覆盖已登记段落和表格，不冒称全稿审计。

CSV的`evidence_ids`按写作工具接口使用分号分隔，TeX中的来源标记仍使用逗号。登记格式和来源ID关联已通过工具解析；人类尚未核读的错误状态原样保留，不通过把状态改成`verified`来消除。

工程核查状态是agent-checked，来源的人类核读状态全部保留unverified，未填写核读人或日期。机器可检查结构和数字一致性，不据此声称人工核实或投稿就绪。科学写作skill的本地通用审计针对Markdown；当前TeX仅做相应的来源/哈希绑定核查，不冒称已通过该审计器的全稿认证。

## 现有证据入口

- [情境对照与旧候选池复查](../CT_CONTEXT_CONTROLS.md)：37维CT情境、完整冻结编码器对照、资源簇主导诊断及受限旧评分结果。
- [独立技术确认预案](../CT_INDEPENDENT_TECHNICAL_CONFIRMATION.md)：精度敏感性、主要技术比较、采集规则与资源预算；具体新队列尚未冻结。

- [P3逐图误差与情境核查](../CT_DEPLOYMENT_FAILURE_CONTEXT_AUDIT.md)：270结果分量复核、22个Demo的时间边界核查、存活朝向掩码及观战信息边界。
- [原有六图案例的CT情境](fixed_case_context.md)：只补充比分、装备和已记录投掷；不改排名、不作战术评分。

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

- TAGNet：[作者CITATION.cff](https://github.com/weyoung-open-lab/TAGNet-CS2/blob/main/CITATION.cff)提供作者、题目、2026年、期刊与DOI。已另行核对出版方登记元数据与Early Access页码1–13；卷期未提供，出版PDF尚未独立核读。
- Deep Sets：[官方论文页](https://papers.nips.cc/paper/2017/hash/f22e4747da1aa27e363d86d40ff442fe-Abstract.html)及其BibTeX导出。文献库作者字段依官方导出。
- Janossy Pooling：[arXiv原始记录](https://arxiv.org/abs/1811.01900)列出作者、题目及ICLR 2019会议引用。
- Scientific Agent Skills：[当前arXiv原始记录](https://arxiv.org/abs/2609.00065)核对作者、年份、题目和DOI；已按该skill要求加入工作流软件说明及参考文献，不将其当作模型有效性的证据。

这是初始引用库，尚未完成相关工作系统核查。没有编造引用或加入无法解析的占位citation key。

## 投掷兼容修复后的当前结果

[兼容诊断与重放说明](../CT_UTILITY_COMPATIBILITY.md)区分事件名、字段值前缀和时间语义。60个旧窗口恢复后，道具情境支持226/246窗口，旧Inferno20窗口仍未知。8份有专用事件的对照中，828/830个查询时刻的派生计数通过，2个派生时刻未使用；原有直接记录保留。原先有效排名及聚类分配已核对一致，既定两套情境矩阵已按v2重放，源权重和聚类中心未重拟合。v1结果与协议保留在3336003及原目录；当前命令读v2协议和输出目录，重放v1须使用对应提交。

## 本轮正文与复现整理

数据表的旧Pending E5已替换为实际结果。方法补了统一匹配损失、源归一化情境距离和主要区间公式，明确装备已在编码器内；讨论逐项回答R1–R4。原事件版本探针和时序证据移入附录，保留完整记录。

[分级复现说明](REPRODUCIBILITY.md)、[独立数值包说明](NUMERICAL_REPLAY.md)和[作者核读入口](AUTHOR_REVIEW.md)区分本机可重算数字、原模型/训练依赖、公开权利及最终批准。论文仍是工作稿，不因自动检查通过而改为可投稿状态。

### 当前情境版本v3

[独立调查](../CT_UTILITY_EVENT_INVESTIGATION.md)解释取消释放与死亡掉落。8份对照的3553个正常释放和830个CT查询计数匹配；死亡掉落反例只有烟雾，不外推HE。v3完整支持245/246窗口，R20在10秒已知，12/15/18/20秒未知。原定两项情境矩阵已重放，源权重、中心、策略和旧结果保留。v2已支持的330660个候选位置、4766个聚类分配保持一致。上节226/246是v2历史结果，当前脚本读取v3；重放v2使用c4991c8。

## 可读工作稿与校验记录

本机PDF：`output/pdf/ct_cross_map_draft.pdf`。[构建/逐页核查记录](../../datasets/evaluation/ct_manuscript_build_report.json)绑定TeX和PDF SHA。主张登记共107条，来源62条；机器格式和绑定一致，但负责的人类核读仍未完成。原有自由文本限制保存在[主张核读注记](claim_review_notes.json)，没有自动赋予证据等级。

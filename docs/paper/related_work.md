# 相关工作核对记录

检索日期：2026-10-25。用途是为当前论文补充针对性叙述综述，不是系统综述或“首次研究”的检索证明。由代理检索和核读，尚未由署名作者核读；主张登记保持`unverified`。Scientific Agent Skills的工作流引用已在主文保留。

## 检索范围与过程

问题：现有工作如何区分部署表示、动作/位置预测、模仿控制和玩家评价；其地图范围及评价单位是什么；哪些结论不能由重建误差推出。

通用学术网页发现查询：`"TAGNet" "Counter-Strike" defensive pattern recognition`、`Counter Strike defensive strategy pattern clustering player trajectories paper`、`Counter Strike cross map tactical representation graph retrieval paper`。随后直接打开arXiv原始记录、作者全文与出版页。搜索总命中数和数据库全量记录未取得，不给出PRISMA计数或覆盖率。只将已打开的原始来源写入主文；搜索摘要、媒体转述和未读论文不作为证据。

优先纳入Counter-Strike部署/移动/团队表征、集合建模、跨域评价、聚类稳定性及不完整相关性判断的方法文献；不将其他游戏的行为聚类当作本研究已经超越的正式基准。尚未完成完整引文追踪。

## 任务、地图与结论边界

| 工作 | 已核读定位与任务 | 地图/评价范围 | 对本研究的约束 |
| --- | --- | --- | --- |
| [TAGNet](https://github.com/weyoung-open-lab/TAGNet-CS2) | 固定上游`1a7ac7c`内作者提供的13页定稿，重点§III、§IV-I；CT开局表示与模式分析 | Dust2；快照重建、固定时序聚合和全体回合聚类 | 区分作者既定设计与本项目整窗重建、学习时序、源拟合聚类；损失数值不能直接对比 |
| [X-Ego](https://arxiv.org/html/2510.19150v1) | §§3.1、4.4、5.1；同步第一视角视频的团队感知与位置预测 | 数据均为Mirage；按回合切分 | 与离线CT快照的输入可见性和终点不同，不能直接比较数字 |
| [Learning to Move](https://arxiv.org/html/2408.13934v1) | §§3–4；Retakes中的移动模仿 | Dust2；多地图支持设想为逐图训练 | 控制器的人类相似性与部署检索相关性是不同问题 |
| [Valuing Player Actions](https://arxiv.org/html/2011.01324v2) | §III-D；NAV图距离和动作价值 | 距离允许方向不对称 | 欧氏/高差不是通行距离；本项目当前不启用未经核实的NAV关系 |
| [Deep Sets](https://papers.nips.cc/paper/2017/hash/f22e4747da1aa27e363d86d40ff442fe-Abstract.html) | 既有来源记录；集合不变性 | 通用方法 | 顺序不变性不是本项目的新算法 |
| [Janossy Pooling](https://arxiv.org/abs/1811.01900) | 当前原始记录；对顺序敏感函数做排列平均 | 通用方法，ICLR 2019 | 本项目整窗联合排列控制需明确归因；玩家排列必须贯穿时间 |

Durst等文献的[出版页](https://onlinelibrary.wiley.com/doi/10.1111/cgf.15173)已核对：*Computer Graphics Forum* 43(8), e15173, 2024，DOI `10.1111/cgf.15173`。X-Ego以当前arXiv预印本元数据引用。Xenopoulos等使用原始arXiv全文和元数据，不猜测会议页码或出版DOI。

## 当前可以写的论证

这些工作提供不同层次的表征与评价依据。本文研究离线CT开局的跨地图共同观测、保持玩家轨迹对应关系的表示对照，以及同候选库的部署检索。其贡献必须由E1–E5的实际结果决定；当前证据不能支持“首次跨地图战术建模”“已识别真实职责”或“重建更好即教练效果更好”。

作者定稿定位：第3–6页的输入、上下文、目标与聚类流程；第9–10页的稳健性比较。原稿明确说明GRU和上下文投影是固定随机聚合器；这不是本项目发现的程序错误。其25维上下文及计数序列、平均聚合、测地距离、非图时序、多种子等比较已经存在，不能作为本项目新增贡献。当前六条件尚未接入完整道具/比分上下文，属于受控观测表示阶段，不能冒称保留原上下文分支的完整复现。

本地PDF SHA256：`15b38b517e3663971d69414100d88207640e18eaa03f2d67dfec0ca7fde0aaf4`，Git blob `804572a21d6d2fee1a416d5efa09f1a505623010`。核读的是作者仓库定稿，未独立核对出版平台版本。

## 跨域、稳定性和检索评价补充

| 来源 | 已核读范围 | 本项目采用的边界 |
| --- | --- | --- |
| [Gulrajani与Lopez-Paz](https://arxiv.org/abs/2007.01434) | 作者arXiv记录/摘要及官方DomainBed说明 | 将模型选择与架构比较分开；不依据新目标结果调配方 |
| [WILDS](https://proceedings.mlr.press/v139/koh21a.html) | 官方PMLR页、摘要和引用导出 | 明确迁移轴；新获取的比赛不自动成为向未来迁移测试 |
| [von Luxburg](https://arxiv.org/abs/1007.1075) | 理想化/实际K-means稳定性及展望；Crossref出版元数据 | 稳定性依赖数据/优化假设，不等于功能职责或参考价值 |
| [Buckley与Voorhees](https://www.nist.gov/publications/retrieval-evaluation-incomplete-information) | 作者机构摘要及Crossref元数据 | 旧已评分池的结果不外推为全库效果；不将未评计零 |
| [Järvelin与Kekäläinen](https://doi.org/10.1145/582415.582418) | 出版方登记的元数据；本文采用分级累计增益概念 | `2^g−1`是本实验明确指定的增益，不冒称照搬其全部公式 |

[元数据核查](../../datasets/evaluation/ct_citation_metadata_audit.json)记录了出版方登记和访问限制。聚类稳定性文献采用Crossref出版年份2010、卷2期3、页235–274；原稿的名义期年与出版年不同，未凭记忆填成卷3。DomainBed的最终OpenReview入口要求浏览器校验，API返回限流；本轮保留已直接核对的2020作者预印本，不猜会议页码或独立确认最终会议信息。

TAGNet的作者、题名、IEEE ToG、2026年、DOI和登记页码1–13已通过出版方存入Crossref的记录核对；卷期和完整上线日期未提供，不补写。1–13按Early Access登记理解，出版PDF仍未独立核读。

主文已补入对应论证，保留`RW`槽位用于FPS检索的进一步引文追踪和作者核读。文献对照不替代独立新系列与独立语义证据。

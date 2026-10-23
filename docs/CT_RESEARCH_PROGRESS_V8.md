# CT 研究 v8：地图核查与导航定位修复

2026-10-23。**已完成开发资料核查和有界定位修复；完整地图语义、独立战术评审及正式盲测仍未验收。** [研究协议](CT_STUDY_PROTOCOL_V8.md)明确跨地图部署类比任务、独立盲评分级、pooled nDCG@5 和正式研究的冻结门槛。现有九系列均为开发资料；真实后端与 T 方训练暂缓。

## 1. 工具与资产版本

按用户要求，本机 `E:/Anaconda` 的 Awpy 从 2.0.2 直接升级到 **3.1.1**，Polars 升到 **2.0.0**，项目依赖和约束同步更新。GPU 训练环境未改动，旧实验代码/权重按原哈希保留。准备中建立的独立试用环境未作为本次验收环境。

旧 Awpy 对六图均报 `Unsupported nav version: 36`；升级后六图全部解析通过。新版入口为 `from awpy import NavMesh`。[3.1.1 发布记录](https://pypi.org/project/awpy/3.1.1/) · [官方导航文档](https://awpy.readthedocs.io/en/latest/nav.html)。

但工具兼容不等于历史地图兼容：本机 CS2 ClientVersion **2000934**、补丁 **14191**，日期 2026-10-20；22 份原始 Demo 流式核对 SHA-256 并读取头部后，**19 份为 14174、3 份为 14165**。全部比赛早于本机地图。

六图 NAV、实体清单和 overview 仅从本机游戏只读提取；VPK、提取文件、工具及 `steam.inf` 均有哈希。观察到的全部 **105 个“地图、place 名称”组合**均存在于当前 `env_cs_place` 清单，这不能证明区域体积和历史版本相同。实体原点不能代替区域边界。

提取使用 [ValveResourceFormat / Source 2 Viewer](https://github.com/ValveResourceFormat/ValveResourceFormat)。工具许可和 Valve 游戏资产再分发权不同；仓库只提交核查数据与代码，不提交游戏地图、导航二进制、雷达图或比赛 Demo。

## 2. 同一批 CT 回合的核查

核查对象与 v7 的有序索引完全相同：9 系列、22 份 Demo、465 个 CT 回合、五个开局快照。既有快照、独立时钟核查和索引均再次验证冻结哈希；排除 T、死亡玩家和此前不合格的短回合。

以下分母是 **11,368 次存活 CT 玩家快照**，不是独立样本数。`other` 采用存活玩家分母，与 v7 按五人名单计算的占位统计不能直接混比。

| 地图 | 存活玩家快照 | 旧特征压为 other | Awpy 原定位覆盖 | 有界定位覆盖 | 仍未知 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ancient | 2,049 | 70.3% | 78.9% | 99.7% | 7 |
| Anubis | 1,017 | 61.1% | 79.9% | 99.4% | 6 |
| Dust2 | 2,062 | 72.6% | 78.5% | 97.9% | 44 |
| Inferno | 2,896 | 53.1% | 73.0% | 99.5% | 14 |
| Mirage | 1,833 | 50.6% | 77.7% | 99.7% | 6 |
| Nuke | 1,511 | 81.0% | 90.7% | 91.9% | 123 |
| 合计 | 11,368 | — | **78.8%** | **98.2%** | **200** |

覆盖率仅指定位器是否返回候选表面，**不是定位正确率或模型效果**。角色评审全部为 `unreviewed`；只登记 BombsiteA/B、CTSpawn/TSpawn 的词面角色候选，不自动给其余路线赋予战术职责。

## 3. 修复原因和行为

Awpy 先筛选 XY 严格落入多边形的区域，再选中心高度最近者，没有最大高度差拒绝规则。细窄高处附近可能查不到区域，或只有下方地面覆盖 XY，导致返回跨层候选。[核对的上游实现](https://github.com/pnxenopoulos/awpy/blob/afb1537f1e8cfe5ebcd54b29fb001707ab2bd5d2/crates/awpy/src/nav.rs)。

项目新增 `NavigationLocator`：

1. 使用 player hull 0 的既有多边形，三角化后计算查询位置的局部表面高度，避免以斜坡中心高度代替。
2. 优先保留符合高度上限、XY 位于区域内部的表面。
3. 没有合格内部表面时才允许有限距离的边缘投影；横向 0/16/32、垂向 64 单位分别核查。这是工程限制，尚不是经专家验证的容差。
4. 返回 `inside` / `bounded_snap`、区域 ID、表面位置和横向/高度残差；超限返回未知。原 NAV 字节与连接边不改，不新增可行走面或伪造路径。

实际 Nuke 案例：Spirit–Falcons 第 18 回合 12 秒的 Crane 位置 `(991.9708, -945.9540, -127.9688)`，原定位为 area 1588，中心高度 `-764`，差 **636.03**；新定位为上层 area 1219，横向偏移 **4.56**，表面高度差 **3.97**。

Nuke 原定位的 249 次中心高度差超过 128 的观测中，**151 次改配到有界表面，98 次拒绝**。这不等于人工确认全部改配正确。另有部分原先未定位的位置恢复，最终 123 次保持未知，其中 **92 次位于 Rafters**。抽查一个 Rafters 点，即使横向搜索扩大到 128、仍保持高度上限 64，也没有候选；未据此放宽正式容差或补边。

当前 Nuke overview 的雷达层分界为 **Z=-495**，开发资料中 Ramp、Secret 均跨分界。雷达层、导航表面和战术楼层须分字段，不能用地名或一个阈值代替全部判断。

## 4. 复跑入口与制品

本机缓存位于忽略目录 `output/tagnet/map_semantics_v8/assets/`。重建时，`$viewer` 指向 Source2Viewer CLI，`$game` 指向游戏的 `game/csgo`，`$map` 为六个地图名之一：

```powershell
& $viewer -i "$game/maps/$map.vpk" --vpk_extensions 'nav,vents_c' -o $assets --threads 1
& $viewer -i "$assets/maps/$map/entities/default_ents.vents_c" -d -o "$assets/$map.entities.txt"
& $viewer -i "$game/pak01_dir.vpk" --vpk_filepath "resource/overviews/$map.txt" -o $assets --threads 1
```

初始核查使用 `scripts/audit_ct_map_semantics.py --help` 中的输入：v7 run、缓存、游戏根目录、提取工具和现有 Demo 目录。其后运行定位核查：

```powershell
& E:/Anaconda/python.exe scripts/audit_ct_navigation_repair.py `
  --inventory datasets/evaluation/ct_map_semantics_v8_report.json `
  --assets-dir output/tagnet/map_semantics_v8/assets `
  --run-dir output/tagnet/ct_grouped_confirmation_v7 `
  --output output/tagnet/map_semantics_v8/navigation_recheck.json
```

输出需用新路径。`ct_map_semantics_v8_report.json` 包含逐地名/高度/覆盖、版本和哈希；`ct_navigation_repair_v8_report.json` 包含三档横向容差、未解决区域、改配实例和源代码哈希；`ct_research_validation_v8.json` 汇总验证证据。

## 5. 验证和资源

- 全套离线回归 **429 passed，3 个既有弃用警告**；新增 13 项覆盖实体解析、存活分母、坏数据拒绝、斜坡、上下层、边界上限、内部优先、坐标变换和非玩家 hull。
- 升级环境 `pip check` 通过；Awpy/Polars 及新增 CLI 依赖的约束相容性检查通过。另从真实 Nuke Demo 重读第 1 回合 tick 5941，五名 CT 的坐标、血量、装备和区域与冻结快照一致。当前环境为 Python **3.13.9**；Python 3.11 的整套锁定环境未重新创建验收。
- v7 的 **18 项冻结代码/权重哈希全部匹配**。没有训练或选择新模型，也不重写既有 v7 结果。
- 全量定位核查约 **19.18 秒**，结束时 RSS **74.99 MiB**，该值不是峰值。设有 2 GiB 启动、1.5 GiB 运行可用内存门槛；未使用 GPU，未下载新比赛。

## 6. 剩余工作

先核对 Nuke Rafters 等残留位置的历史补丁静态几何，取得兼容资产或明确采用已核实的新版本研究设计；对有限边缘投影补做碰撞/关键位置检查，防止隔墙贴到附近表面。随后完成六图职责映射与 12 查询真实标注试点，再冻结模型配方、主比较、采集划分和样本量。

定位器目前是离线语义特征的候选组件，尚不能证明通行距离正确、战术检索有效或完整 CT 泛化验收通过。不得仅根据目标比赛的玩家轨迹补造导航空洞。

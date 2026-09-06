<div align="center">

# 🎯 CS2 Coach Agent
### *由多智能体驱动的 CS2 职业赛事战术复盘系统*

[English](README_EN.md)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6B35?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Milvus](https://img.shields.io/badge/Milvus-VectorDB-00A1EA?style=flat-square)](https://milvus.io/)
[![Celery](https://img.shields.io/badge/Celery-Redis-37814A?style=flat-square&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

历史刀局污染已完成重建并切换：原有 20 场、49 图现在包含 1,019 个正式回合，图谱、Milvus、56 名选手画像和 5,308 条战术银标已核对一致。152 项离线测试通过。原始数据快照与失败结果均保留，详见 [历史修复与重新冻结](docs/HISTORICAL_DATA_REBUILD_V2.md)。

新语料上的 16 题、160 条检索结果已按 AI 辅助事实标签重新运行，仍属于已观察开发集；独立审核与泛化效果待验证。新增 2 场、5 图在修复后以 111 个正式回合通过回归，首次失败记录见 [新比赛验收](docs/NEW_MATCH_VALIDATION_V3.md)。

Coach 优先级对照已完成 6 图、5 场比赛的开发样本试跑：固定模型 `qwen3.8-flash` 调用 6 次，提供商报告本轮使用 4,939 token。匿名材料与空白评分表已生成，至少两位独立人工评审尚待完成，模型增益指标保持为空。见 [盲评协议与运行记录](docs/COACH_BLIND_EVALUATION.md)。后续 [AI 事实审核](docs/COACH_FACT_AUDIT.md) 已修复攻守分母与己方受闪口径，原始盲评包继续保留，人工评分需使用重新冻结的修正版。

生产模型入口已加入跨进程 SQLite 用量账本，默认本地上限 30,000 token / 100 次尝试；超时、额度拒绝或用量缺失会暂停后续调用并保留规则分析，页面可查看状态。提供商剩余免费额度仍未知。见 [预算与故障边界](docs/MODEL_BUDGET_BOUNDARIES.md)。

此前画像阶段已完成参赛分母与归属修复、离线测试环境：当时 49 张地图的 1,023 条回合记录名单完整（其中 4 个赛前刀局已在本轮修正），87 项离线测试通过，独立前端构建通过。远端 CI 已通过，[查看运行记录](https://github.com/Zzz0zzZ0/CS2-coach-agent/actions/runs/34031162026)。详见 [执行进度与验收](docs/IMPLEMENTATION_PROGRESS.md)、[画像数据契约](docs/PLAYER_PROFILE_DATA_CONTRACT.md) 与 [离线复现](docs/OFFLINE_VALIDATION.md)。

---

## 📖 项目简介

**CS2 Coach Agent** 是一个以 **多智能体状态机** 为核心、具备 **高级 RAG 战术检索能力** 的 CS2 职业赛事智能分析系统。

它能够：
- 直接吃入 `.dem` 录像文件，通过 `demoparser2` 自动解析每一回合的击杀链、道具落点、闪光致盲序列和下包行为。
- 内置 **HLTV 数据爬虫与录像下载器**，支持自动化获取职业赛事高价值 Demo 数据集。
- 驱动 **Supervisor（受控 Tool Calling）→ Tools → Router → 并行任务检索 → Critique → Analyst → Coach → Verifier** 构成一条带有反馈式 **Refine Loop** 的端到端战术推演流水线；知识摄取必须通过验证、人工批准和配置开关三重闸门。
- Critique 节点在检索质量低于阈值时触发 **反馈式重试回路**；达到最大尝试次数后会保留低质量标记并继续分析，不伪装成达标。
- 由代码先计算并报告可验证的击杀、首杀、攻守分边和下包转化；`qwen3.8-flash` 只能从白名单中选择训练优先级，不能直接编造报告事实。
- 同时支持 **FACEIT / 5E Webhook 数据流** 和 **实体 `.dem` 文件上传** 两种数据接入模式。
- 全部耗时任务通过 **Celery + Redis** 异步消息队列处理，支持高并发与横向扩展。

---

## 🏗️ 系统架构

```
          ┌─────────────────────────────────────────────────────┐
          │              FastAPI Web Service (app/main.py)      │
          │                                                     │
          │   POST /api/webhook/match-end  (JSON Payload)       │
          │   POST /api/upload-demo        (.dem 实体文件上传)  │
          │   GET  /api/tasks/{task_id}    (查询异步任务状态)   │
          └──────────────────────┬──────────────────────────────┘
                                 │ Celery task.delay() 推送
                                 ▼
                          ┌────────────┐
                          │  Redis MQ  │
                          └──────┬─────┘
                                 │ 分发给 Celery Worker
                                 ▼
          ┌──────────────────────────────────────────────────────┐
          │        LangGraph 多智能体状态机 (Agentic Workflow)   │
          │                                                      │
          │   [Supervisor] ──► [Tools] ──► [Router] ──► [Task Retrieval] ──► [Critique] ──► [Analyst] ──► [Coach] ──► [Verifier]
          │                    │                    │                  │
          │                    │       缺失任务?     │                  │
          │                    ◄──── Refine only failed tasks             │
          │               首杀/道具/回合/地图任务                  引用与事实校验
          └──────────────────────────────────────────────────────┘
                 │                       ▲
                 ▼                       │
          ┌──────────┐          ┌───────────────┐
          │  Milvus  │          │ DashScope LLM │
          │ 向量知识库│          │ (通义千问)    │
          └──────────┘          └───────────────┘
```

---

## ⚡ 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **Web 层** | FastAPI + Uvicorn | 异步 Webhook 服务，支持 `.dem` 文件上传及任务状态查询 |
| **异步队列** | Celery + Redis | 企业级后台耗时任务队列，实现高并发与横向扩展 |
| **智能体编排** | LangGraph (StateGraph) | 受控 Tool Calling → 确定性工具 → 并行检索 → 规则/LLM 评审 → 分析 → 教练 → 引用校验 |
| **检索 (RAG)** | Milvus 2.6 + LangChain | dense + 原生 BM25 混合召回、RRF、父子上下文、纠错检索与证据追踪 |
| **LLM** | 阿里云 DashScope / 通义千问 | `qwen3.8-flash` 模型推理（通过 OpenAI 兼容接口接入） |
| **Embedding** | FastEmbed + ONNX | 本地多语言 embedding，不消耗 DashScope embedding 额度 |
| **数据采集** | DrissionPage | HLTV 赛事数据爬取与 `.dem` 自动化下载 |
| **Demo 解析** | awpy + demoparser2 | CS2 录像帧事件精准提取（击杀链/道具/闪光/下包） |
| **架构规范** | DDD (领域驱动设计) | 高内聚低耦合的 Clean Architecture 目录规范 |

---

## 🔬 技术实现详解

### 1. 从 Demo 到教练建议的数据流

```text
.dem / Webhook JSON
        │
        ▼
TacticalDemoParser
        │  round_end / player_death / grenade / flash / bomb events
        ▼
结构化 MatchWebhookPayload
        │
        ├── Tools：计算确定性指标
        ├── Milvus：混合文本检索
        ├── GraphRAG：关系路径与社区摘要检索
        │
        ▼
Critique：任务覆盖、地图匹配、证据数量与相关性评分
        │  只重试缺失任务，最多三次
        ▼
Analyst：只陈述数据事实
        ▼
Coach：模型选择白名单训练优先级，代码生成证据化建议
        ▼
Verifier：校验当前 [C#]、历史 [E#] 引用和无证据建议
```

Demo 解析层只保存可观测事件，不直接推断“某个道具导致了胜利”。Analyst 与 Coach 的最终文字由确定性事实模板生成；模型只决定白名单训练主题的排序。这使原始事实、模型选择和教练建议在系统中可以区分。

### 2. LangGraph 状态机与受控 Agent

所有节点通过 `GraphState` 传递状态，关键字段包括：

| 字段 | 作用 |
|------|------|
| `metrics` | 代码计算的战队比分、有效击杀、首杀转化、道具和下包指标 |
| `current_evidence` | 当前上传 Demo 的确定性证据，映射为 `[C#]` |
| `analysis_plan` | Router 生成的 opening / utility / round flow / map context 任务 |
| `retrieval_task_results` | 每个检索任务的覆盖度、来源数量和告警 |
| `retrieval_evidence` | Milvus/GraphRAG 历史对照证据，映射为 `[E#]` |
| `agent_trace` / `tool_trace` | 前端展示 Supervisor、Tools 和检索执行过程 |
| `verification_report` | 未知引用、缺失引用和审核状态 |

Supervisor 可以通过白名单 Tool Calling 选择分析模式，但不能创建新节点、执行代码、访问网络或直接写入知识库。Tool Calling 失败时使用确定性 fallback，因此模型输出不会改变工作流拓扑。

### 3. Milvus Hybrid RAG

当前向量检索集合为 `cs2_tactical_knowledge`，每条文档保留 `map`、`match_id`、`round_number`、`tactic_type`、`parent_id` 和 `parent_content` 等元数据。

一次检索包含以下步骤：

1. 默认直接使用 Router 生成的专业术语查询；仅在 `LLM_AUXILIARY_CALLS_ENABLED=true` 时增加 LLM 查询改写。
2. 使用本地 FastEmbed/ONNX 模型生成 384 维 dense embedding，避免调用付费 embedding API。
3. Milvus 原生 BM25 对文本字段进行稀疏检索，dense 与 sparse 结果使用 RRF 合并。
4. 查询原文、改写查询和任务变体共同召回，按 lexical overlap、rank 和 parent-context bonus 重新排序。
5. 使用稳定的 evidence key 去重，并为每个任务优先保留少量证据，避免某一个主题占满上下文。
6. Critique 只把未覆盖的任务加入下一次检索，不重复执行已经通过的任务。

当 Milvus 不可用时，系统仍可用 GraphRAG 事实路径继续工作；当 GraphRAG 数据库不存在时，则自动退回 Milvus。

### 4. GraphRAG 两级检索

GraphRAG 使用标准库 SQLite 作为本地图谱侧车，不改变 Milvus 的职责。

```text
nodes:
  match → map → round ┬→ event → player
                      └→ tactical_sequence → event/player

edges:
  HAS_MAP / HAS_ROUND / KILL / USES_UTILITY /
  FLASH_BLIND / PLANTS_BOMB / KILLER / VICTIM /
  HAS_TACTICAL_SEQUENCE / SUPPORTED_BY / INVOLVES_PLAYER
```

- Local Search：以地图、任务和关键词筛选回合，沿事件路径及 `round → tactical_sequence → evidence/player` 路径返回证据。
- Community Summary：按“地图 × 主题”聚合回合，当前主题包括 overview、opening、utility、round_flow。
- Global Search：对多个社区摘要进行全局排序，返回社区摘要及其回合来源 ID；前端保留原始图证据与确定性教练简报供人工对照。

社区摘要采用确定性抽取式统计，包含回合数、比赛数、击杀、首杀、道具、下包、战术银标、回合胜者和首杀玩家等事实。它不会把少量样本直接表达为“所有职业队都这样打”。

### 5. 前端复盘工作台

`frontend/` 是独立的 React + Vite 应用，采用 `/api` proxy 连接 FastAPI，不复制后端业务逻辑：

- 上传页提交 `.dem` 和 `analysis_mode`，后端返回 Celery `task_id`。
- 前端每两秒轮询 `GET /api/tasks/{task_id}`，在 SUCCESS 后展示 `analysis` 结果。
- Dashboard 分开展示当前 Demo `[C#]` 与历史对照 `[E#]`；验证未通过时任务显示“质量待审查”。
- GraphRAG 面板通过只读接口加载地图、节点/边、Global Search、选手画像和战队对比结果。
- 子图使用 SVG 绘制，避免引入大型图可视化依赖；移动端通过 CSS breakpoint 降级为单列布局。

### 6. 可靠性和审核边界

- 指标计算先于 LLM；环境/自杀/队伤不会计为有效击杀，战队比分、首杀转化、道具和下包均由代码计算。
- Critique 只评价证据相关性和覆盖度，不让模型决定是否“战术正确”。
- Verifier 不调用 LLM，检查未知 `[C#]/[E#]`、未引用建议，以及当前比赛结论是否误用历史证据。
- 自动知识摄取默认关闭，同时要求高质量来源、显式人工批准和 Verifier 通过。
- Demo、解析输出、SQLite 图谱、Milvus 卷和 `.env` 均属于本地运行数据，不进入 Git。

---

## 🚀 快速开始

### 1. 克隆并初始化环境

```bash
git clone https://github.com/Zzz0zzZ0/CS2-coach-agent.git
cd CS2-coach-agent
make bootstrap
```

`make bootstrap` 会创建 Python 3.11 虚拟环境、安装运行/开发依赖并启动 Redis/Milvus 基础设施。

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的阿里云 DashScope API Key 和基础设施配置：

```env
# DashScope / OpenAI 兼容接口
DASHSCOPE_API_KEY="sk-your-key-here"
MODEL_NAME=qwen3.8-flash
LLM_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=1400
LLM_ENABLE_THINKING=false
LLM_AUXILIARY_CALLS_ENABLED=false

# Milvus 向量数据库
MILVUS_URI="http://localhost:19530"
MILVUS_TOKEN=""

# Celery 消息队列（需要本地运行 Redis）
CELERY_BROKER_URL="redis://localhost:6379/0"
CELERY_RESULT_BACKEND="redis://localhost:6379/1"
```

也可以启动前端后，在“提交比赛 Demo”区域直接输入 Key。前端调用 `PUT /api/settings/llm/key`，密钥只写入本机 `data/runtime/dashscope_api_key`（权限 `0600`），不会保存到浏览器、Git、API 响应或 Celery 任务载荷；API 与 Worker 会在下一次模型调用时动态读取，无需重启。该写入接口仅接受本机回环地址请求，`GET /api/settings/llm` 只返回是否已配置，不回传密钥。

### 3. 初始化战术知识向量库

```bash
python scripts/seed_knowledge.py
```

> 这一步会读取 `data/demos/*.dem`，按比赛摘要、首杀证据和回合事件生成结构化文档，并替换 `cs2_tactical_knowledge` 集合中的旧种子。可先执行 `python scripts/seed_knowledge.py --dry-run` 查看文档数量。

### GraphRAG 图谱侧车

GraphRAG 使用本地 SQLite 保存由 Demo 解析出的比赛、地图、回合、事件、玩家和战术序列关系，不依赖付费 embedding，也不让 LLM 臆造图谱关系：

```bash
make graph-build
```

`make graph-build` 会同时重算当前 silver 战术标签，并把它们写为 `tactical_sequence` 节点，通过 `SUPPORTED_BY` 与原始事件连接。分析请求会自动并行检索 Milvus 与图谱；命中的标签及其 `label_source`、置信度会以 `Graph ... Evidence` 和 `[E#]` 引用进入现有 Analyst、Coach、Verifier 链。`weak_rule` 只作为候选序列，不视为人工确认战术。没有 `data/graph/cs2_graph.sqlite` 时自动退回 Milvus。

同一个 SQLite 图谱还提供跨比赛分析：选手画像聚合击杀、死亡、助攻、首杀/首死、补枪、道具、下包和六类战术序列参与，并可按地图、T/CT、对手筛选或比较两名选手在相同筛选下的指标与样本组成；战队对比则把战术序列统一换算为每 100 个实际参赛回合，避免不同比赛数量造成总量偏差。战术切片计算首杀后胜率、丢首杀翻盘率、补枪回合胜率、Post-plant、Retake contact 和 Execute candidate 的回合转化，同时列出首杀、补枪和道具协同的选手责任分布。自然语言搜索同时支持战队和选手中文教练简报，每个结果都保留 `graph:{match}:{map}:{round}` 来源。当前指标是描述性统计，不宣称战术因果。没有胜方的 `round_end` 被视为技术暂停或回合恢复标记，不计入正式回合。若 GOTV Demo 缺少原生 `player_blind`，解析器会在每次 `flashbang_detonate` 的前后 tick 比较 `flash_duration`，恢复受闪者、投掷者、队伍、区域和持续时间，并以 `source=flash_duration_delta` 标记来源。同一 tick 只有一颗闪时投掷者可唯一归因；多颗闪同时爆炸时则保留全部 `attacker_candidates` 并标记 `attribution=simultaneous_flash_candidates`，不虚构唯一投掷者。

画像页和自然语言选手查询共用确定性总结，包含基础表现、行为结论、样本范围、已知结果分母和分组引用。所问行为无记录时保持原主题，不生成站位、沟通或职责诊断；当前 26 条总结查询通过工程证据一致性检查，尚未代替人工盲评。见 [总结契约与验收](docs/PLAYER_GROUNDED_SUMMARY.md)。

选手画像新增个体行为与回合结果面板：首杀、首死、补枪、道具、致盲、下包分别比较“观测到 / 未观测到”的回合胜率，并展示原始胜负数、未知结果及胜负回合引用。重复事件按回合去重，未知结果不进入胜率分母；两组未经条件匹配，差异只表示关联。56 名选手的六类行为通过原始记录审计，见 [口径与复现](docs/PLAYER_BEHAVIOR_OUTCOMES.md)。

选手对比支持跨队选择，同时展示双方比赛 / 地图 / 回合数、首杀机会数、地图 × 阵营 × 对手组成、共同参赛回合与共同条件覆盖率。归一化只调整样本量，样本占比不同会明确提示；不把描述性差异直接解释为能力排序或统计显著性。名单估算、无样本和比赛日期缺失保持可见，完整参赛覆盖与抽样事件引用分开计算。详见 [画像与对比数据口径](docs/PLAYER_PROFILE_DATA_CONTRACT.md)。

Global Search 会先从自然语言中识别战队、地图、T/CT 和对手，再把对应战术切片作为最高优先级的结构化证据返回；包含“比较/对比”等意图且出现两支战队时，会生成同条件战术对照。示例：`猎鹰 Dust2 T侧首杀后胜率`、`猎鹰面对绿龙时的回防表现`、`对比 Spirit 和 Vitality 在 Nuke CT侧的补枪回合`。该步骤完全确定性执行，不新增 LLM 调用。

### 4. 启动 API 与 Worker

```bash
make dev
```

`qwen3.8-flash` 默认开启深度思考；本项目将其关闭，并默认只让 Coach 调用一次模型。Supervisor、查询路由、Critique 与 Analyst 使用确定性本地逻辑，单次生成上限为 1400 token，前端显示本次模型 token 用量。只有显式设置 `LLM_AUXILIARY_CALLS_ENABLED=true` 才启用查询改写、LLM Critique 等额外调用。额度耗尽或供应商拒绝请求时不重试模型调用，Coach 回退到本地优先级规则。本地开发默认使用 Celery `solo` pool，避免 macOS `fork` 与 FastEmbed/ONNX 原生运行库冲突。Linux 部署可显式使用 `CELERY_POOL=prefork CELERY_CONCURRENCY=4 make worker`。上传产生的临时 Demo 会在任务结束后自动删除。

### 5. 启动前端复盘工作台

另开一个终端执行：

```bash
make frontend-install
make frontend
```

浏览器打开 `http://localhost:5173`。前端提供 Demo 上传、异步进度、指标卡片、Analyst/Coach 报告、证据引用、GraphRAG 子图、Global Search、跨比赛选手画像、五队战术对比和上下文战术切片；战队查询会先展示确定性中文教练简报，再保留原始图证据。`[G#]` 优先引用查询指标对应的回合；还可按首杀、补枪、道具、爆弹、下包后、回防和胜负结果筛选关键回合样本。点击样本会展开事件与战术标签时间线，并按同地图、同阵营、相反胜负结果以及战术标签/包点重合度推荐成功—失败对照回合。Vite 会把 `/api` 请求代理到 `8001`。

新增只读 GraphRAG 展示接口：

```text
GET /api/graph/stats
GET /api/graph/maps
GET /api/graph/search?q=... # 返回 answer 中文简报与 results 原始证据
GET /api/graph/round?source_id=graph:2396609:Dust2:1&team=Falcons # team 可选；提供相反结果的相似回合
GET /api/graph/subgraph?map_name=Mirage
GET /api/graph/players?team=Falcons
GET /api/graph/players/{steamid_or_nickname}?map_name=Dust2&side=T&opponent=Spirit
GET /api/graph/players/compare?players={id1},{id2}&map_name=Dust2&side=T
GET /api/graph/teams/compare?teams=Falcons,Spirit,Vitality,FURIA,MOUZ
GET /api/graph/teams/Falcons/tactics?map_name=Dust2&side=T&opponent=Spirit
```

### 6. 使用方式

**方式 A：直接分析本地 Demo（推荐开发使用）**
```bash
make analyze DEMO=data/your_match.dem
```

**方式 B：获取较新的职业比赛 Demo**

默认查询最近 7 天、HLTV 至少 2 星且明确提供 Demo 的已结束比赛；如果窗口内没有可用 Demo，会自动扩大到最近 30 天，并把比赛元数据写入 `data/demos/manifests/`。

```bash
# 只抓取比赛目录，不下载大文件
make fetch-demos ARGS="--days 7 --min-rating 2 --max-matches 10"

# 下载并解压 .dem 文件（需要本机有 unar、7z、unrar 或 bsdtar 之一）
make fetch-demos ARGS="--days 30 --min-rating 2 --max-matches 10 --download"

# 按已审核的固定比赛清单下载，便于复现实验数据集
make fetch-demos ARGS="--selection-file datasets/selections/five_teams_recent_20_v1.json --download"
```

下载器只接受 HLTV 比赛页明确暴露的官方 Demo 链接，不会把普通比赛页面误当作录像源；下载完成后会保留按比赛命名的 manifest，重复执行默认跳过已有 manifest，使用 `--force` 才会重新下载。

**方式 C：启动 Web 服务，接收第三方 Webhook**
```bash
make dev
```

随后发送 POST 请求到 `http://127.0.0.1:8001/api/webhook/match-end`：

```json
{
  "match_id": "match-001",
  "map_name": "Mirage",
  "rounds": [...]
}
```

或者上传实体录像文件：
```bash
curl -X POST http://127.0.0.1:8001/api/upload-demo \
  -F "file=@data/sample.dem"
```

查询异步任务状态：
```bash
curl http://127.0.0.1:8001/api/tasks/{task_id}
```

---

## 📁 项目结构

```
CS2-coach-agent/
├── app/                           # DDD 架构主应用
│   ├── main.py                    # FastAPI 服务入口点
│   ├── api/                       # 接入层：FastAPI 路由与依赖注入
│   │   ├── dependencies.py        # FastAPI 兼容依赖导出
│   │   └── routers/
│   │       ├── webhooks.py        # POST /api/webhook/match-end
│   │       ├── uploads.py         # POST /api/upload-demo
│   │       ├── graph.py           # GET  /api/graph/*
│   │       └── tasks.py           # GET  /api/tasks/{task_id}
│   ├── core/                      # 核心配置
│   │   ├── config.py              # 环境变量统一管理 (Settings)
│   │   ├── providers.py           # LLM / Milvus provider
│   │   └── celery_app.py          # Celery 应用实例
│   ├── domain/                    # 领域模型
│   │   ├── match_models.py        # Pydantic 数据验证 Schema
│   │   └── analysis_models.py     # 指标与分析结果模型
│   ├── services/                  # 应用服务层
│   │   ├── rag_service.py         # RAG：实体约束 + dense/BM25 混合检索
│   │   ├── graph_rag_service.py    # GraphRAG：图谱、社区摘要与 Global Search
│   │   ├── metrics_service.py     # 确定性比赛指标计算
│   │   ├── analysis_pipeline.py   # 统一分析入口
│   │   ├── parser_service.py      # Demo 解析器：demoparser2 封装
│   │   └── tasks.py               # Celery 异步任务定义
│   ├── scrapers/                  # 数据采集层
│   │   ├── hltv_scraper.py        # HLTV 赛事元数据爬虫
│   │   └── demo_downloader.py     # 职业录像自动化下载器
│   └── agentic/                   # 智能体编排层
│       ├── states.py              # GraphState 全局状态定义
│       ├── workflow.py            # LangGraph 状态机构建 (含 Refine Loop)
│       └── nodes/                 # 受控 Agent 节点与确定性工具节点
│           ├── supervisor_node.py # Supervisor：选择受控分析模式
│           ├── tool_node.py       # Tools：先执行确定性指标计算
│           ├── router_node.py     # Router：元数据抽取 & 过滤信号
│           ├── retrieve_node.py   # Retrieve：向量检索调度
│           ├── critique_node.py   # Critique：检索质量评审 (0.0-1.0)
│           ├── analyst_node.py    # Analyst：确定性事实报告
│           ├── coach_node.py      # Coach：白名单优先级 + 证据建议
│           └── verify_node.py     # Verifier：引用和事实校验
├── scripts/                       # 工具脚本
│   ├── seed_knowledge.py          # Milvus 知识库初始化种子脚本
│   ├── build_graph.py             # GraphRAG 图谱与社区摘要构建
│   ├── evaluate_retrieval.py      # RAG 离线 smoke evaluation
│   ├── evaluate_tactical_queries.py # 战术自然语言查询契约评测
│   ├── fetch_recent_demos.py      # HLTV 职业 Demo 获取入口
│   ├── analyze_local.py           # 本地 Demo 直接分析入口
│   └── test_webhook.py            # Webhook 接口测试脚本
├── datasets/evaluation/           # 固定查询集与可复现评测报告
├── test_main.py                   # 端到端集成测试
├── test_agentic.py                # Agent 编排与工具测试
├── test_graph_rag.py              # GraphRAG 路径与 Global Search 测试
├── .env.example                   # 环境变量模板
├── Makefile                        # 简化开发入口
├── requirements.txt               # Python 依赖
├── requirements-dev.txt            # 开发与测试依赖
├── frontend/                       # React + Vite 复盘工作台
│   ├── src/main.jsx                # Dashboard 与 GraphRAG 展示
│   ├── src/api.js                  # 后端请求封装
│   └── src/styles.css              # 深色战术控制台样式
├── data/                          # .dem 录像文件存放（本地，不入库）
└── output/                        # 分析结果输出（日志/JSON，不入库）
```

---

## 🎭 智能体角色设计

### 🧭 Router（元数据抽取器）
> 使用规范化输入中的地图元数据生成过滤信号供下游 Retrieve 节点使用，避免让 LLM 重复抽取已有字段。

### 🧠 Supervisor / Tools（受控编排与工具层）
> 默认使用确定性 Supervisor 选择分析模式；开启辅助模型调用后，也只能通过白名单 `select_analysis_plan` 选择既有模式与检索任务。Tools 节点先运行确定性指标计算。

### 📚 Retrieve（战术知识检索器）
> 调用 `KnowledgeBaseClient`：默认直接使用 Router 查询，经 Milvus 原生 dense + BM25 混合检索并保留父摘要与证据来源；查询改写是可选的额度开销。

知识库默认使用 Milvus 原生 dense + BM25 混合检索，并在证据中保留比赛/地图父摘要；旧的 dense 集合仍可通过 `RAG_HYBRID_ENABLED=false` 走兼容 fallback。使用 `make eval-rag` 运行固定查询的离线 smoke evaluation。

### ⚖️ Critique（检索质量裁判）
> 由代码评估任务覆盖、地图匹配、战队匹配和证据数量。**评分低于 0.7 时，评审反馈会加入下一轮查询，最多重试三次。**

### ✅ Verifier（事实与引用校验器）
> 不调用 LLM，检查报告中的 `[E#]` 是否存在、是否有未知引用，以及关键建议是否缺少证据标记。

### 🔬 Analyst（确定性事实报告）
> 不调用 LLM，只报告比分、攻守分边、首杀转化、下包转化、拆包和道具计数；缺失指标会明确标记，不给出主观因果。

### 🎯 Coach（受控训练决策）
> `qwen3.8-flash` 只通过 `select_coaching_priorities` 在首杀后续、下包后处理、道具复核和攻守转换中选 2–3 项；最终报告与 `[C#]` 引用由代码生成。模型不能添加角色、站位、道具效果或战术因果。

### 🔐 知识摄取审核闸门
> 自学习入库默认关闭。只有 `AUTO_INGEST_ENABLED=true`、输入标记 `extra_data.knowledge_approved=true`、来源标记为高质量且 Verifier 通过时，分析任务才会提交入库；否则结果会返回 `knowledge_review.status=pending_review`，可由人工确认后调用手动 `/api/knowledge/ingest`。

### ✅ 本地验证

```bash
make test       # 单元与集成测试
make eval-rag   # 固定查询的 Milvus RAG 评估
make eval-tactics # 30 条 GraphRAG 战术查询契约评测
make eval-players # 20 条上下文选手查询契约评测
make eval-v1      # 50 条契约 + 50 条检索查询的五路消融评分
make eval-negatives # 独立的 12 条 synthetic 开发负例
make eval-holdout # 冻结的 30 条 held-out 回归验收（原始基线另存）
make graph-build
make silver-dataset # 生成带置信度与证据来源的战术银标数据集
```

GraphRAG 当前采用确定性抽取式社区摘要；摘要只概括解析到的事实，并保留回合来源，不把小样本观察直接升级为职业战术定律。

`make silver-dataset` 默认输出 `datasets/silver/v0.3/`，已有目录拒绝覆盖；复现请用 `ARGS="--output-dir 新目录"`。v0.3 沿用 `datasets/selections/five_teams_recent_20_v1.json` 的 20 场比赛，修正解析边界后为 49 张地图、1,019 个正式回合和 5,308 个战术银标；v0.1 / v0.2 作为历史快照保留。首杀和下包阶段来自直接事件事实；补枪、Utility Burst 与 Retake Contact 来自明确的时间窗规则；只有 T 方道具序列后成功下包才会追加弱监督的 Execute Candidate。所有标签都保存规则版本、置信度、审核状态和证据事件 ID。该数据集定位为可复现的 silver labels，不宣称是职业教练人工标注的 gold labels。

### 统一 GraphRAG 评测

`datasets/evaluation/tactical_queries_v1.json` 包含 30 条战队战术查询，`datasets/evaluation/player_queries_v1.json` 包含 20 条选手画像、地图/阵营/对手切片和双人对比查询。`datasets/evaluation/retrieval_queries_v2.json` 另含 50 条检索查询，覆盖 7 张地图 × 4 种意图、5 支目标战队、5 名代表选手、8 条双语改写和 4 条无答案负例。标签只使用 Demo 中可观察的地图、实体和证据类型，不需要主观人工战术标注。

`make eval-v1` 在 50 个结构化契约和 152 个检索检查点上统一比较 no-RAG、community-only、vector-only、graph-only 与 hybrid，全程禁用远程查询改写。当前结果：graph-only 与 hybrid 均为 100.00、vector-only 77.72、community-only 73.76、no-RAG 4.46。Vector 的 50 条检索查询本身为 50/50；较低综合分来自它无法生成 45 条结构化战队/选手契约，而不是召回失败。统一报告写入 `datasets/evaluation/cs2_coach_v1_report.json`，Vector 独立报告写入 `datasets/evaluation/retrieval_v2_report.json`，解释性总结见 [`docs/V1_EFFECT_REPORT.md`](docs/V1_EFFECT_REPORT.md)。这是 silver-standard 工程评分，不等同于教练对战术结论或选手水平的人工 gold evaluation，也不证明因果关系。

冻结后首次运行的 `retrieval_queries_holdout_v1.json` 包含 30 条不同措辞、不同选手和更难负例。Graph-only 与 hybrid 的 held-out 综合分均为 97.99：27/27 正例通过，3 条开放式未知实体/跨领域负例均误召回。Vector-only 检索为 24/30、93/99 检查点，综合分 65.77。该原始基线保留在 `datasets/evaluation/cs2_coach_holdout_v1_report.json`。冻结查询不得修改；后续修复使用独立开发样例，并保留复测记录。


### 负例边界修复复测（2026-09-06）

独立 synthetic 开发负例 12/12 通过；原开发集 Vector、Graph、Hybrid 仍为 50/50，结构化契约仍为 50/50。最终 held-out Graph 与 Hybrid 为 **30/30、99/99 检查点、综合分 100.00**：原有 27 个正例全部保留，3 个负例全部正确拒答。Vector 为 **27/30、96/99、67.79**，原已通过用例无回退，仍有 3 个主题匹配检查失败。

本轮实际复测 **两次**：首次发现普通描述词和显式地图上下文被误拒答，未通过验收；随后在独立正例上复现并恢复上下文语义，再完成最终验收。首次失败报告为 `datasets/evaluation/cs2_coach_holdout_v1_attempt1_report.json`，最终报告为 `datasets/evaluation/cs2_coach_holdout_v1_fixed_report.json`。原始基线和冻结查询保持不变；这属于冻结回归验证，不是新的完全盲测或未见比赛泛化证明。

本轮 `make test` 为 80 项通过、3 个依赖告警，前端构建通过；所有检索评测均未调用远程模型。验证细节见 [修复验收记录](docs/NEGATIVE_RETRIEVAL_FIX.md)。

实体约束覆盖英文画像、名称与地图、对手和比较句式，并保留中文别名。图查询先核对索引中的选手/战队；向量证据使用完整名称边界，不能用相似昵称代替。无上下文时，`match`、`professional` 等通用词不再足以触发检索；调用方显式提供的地图/比赛过滤仍作为上下文。该规则是有限查询语法，不是通用实体识别器。

改进路线见 [工程展示与研究路线](docs/PROJECT_IMPROVEMENT_ROADMAP.md)：优先独立比赛验证、公平消融、人工审阅与无密钥 CI。当前工程满分不等于战术建议正确率或未见赛事泛化能力。

---

## 📝 License

MIT © 2026

---

<div align="center">
<sub>Built with ❤️ for the CS2 competitive scene.</sub>
</div>

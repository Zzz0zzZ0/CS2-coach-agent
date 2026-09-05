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

---

## 📖 项目简介

**CS2 Coach Agent** 是一个以 **多智能体状态机** 为核心、具备 **高级 RAG 战术检索能力** 的 CS2 职业赛事智能分析系统。

它能够：
- 直接吃入 `.dem` 录像文件，通过 `demoparser2` 自动解析每一回合的击杀链、道具落点、闪光致盲序列和下包行为。
- 内置 **HLTV 数据爬虫与录像下载器**，支持自动化获取职业赛事高价值 Demo 数据集。
- 驱动 **Supervisor（受控 Tool Calling）→ Tools → Router → 并行任务检索 → Critique → Analyst → Coach → Verifier** 构成一条带有反馈式 **Refine Loop** 的端到端战术推演流水线；知识摄取必须通过验证、人工批准和配置开关三重闸门。
- Critique 节点在检索质量低于阈值时触发 **反馈式重试回路**；达到最大尝试次数后会保留低质量标记并继续分析，不伪装成达标。
- 由代码先计算可验证的击杀、首杀和回合指标，再通过 **HLTV 首席数据师** 与 **B1ad3 风格教练** 完成报告和战术复盘；缺失数据不会被伪造为 ADR/KAST。
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
| **LLM** | 阿里云 DashScope / 通义千问 | `qwen-plus` 模型推理（通过 OpenAI 兼容接口接入） |
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
Coach：基于数据和证据生成战术建议
        ▼
Verifier：校验 [E#] 引用和无证据建议
```

Demo 解析层只保存可观测事件，不直接推断“某个道具导致了胜利”。因果判断留给 Analyst/Coach，并要求引用证据。这使原始事实、模型解释和教练建议在系统中可以区分。

### 2. LangGraph 状态机与受控 Agent

所有节点通过 `GraphState` 传递状态，关键字段包括：

| 字段 | 作用 |
|------|------|
| `metrics` | 代码计算的回合、击杀、首杀和玩家指标 |
| `analysis_plan` | Router 生成的 opening / utility / round flow / map context 任务 |
| `retrieval_task_results` | 每个检索任务的覆盖度、来源数量和告警 |
| `retrieval_evidence` | 统一的可追溯证据，最终映射为 `[E#]` |
| `agent_trace` / `tool_trace` | 前端展示 Supervisor、Tools 和检索执行过程 |
| `verification_report` | 未知引用、缺失引用和审核状态 |

Supervisor 可以通过白名单 Tool Calling 选择分析模式，但不能创建新节点、执行代码、访问网络或直接写入知识库。Tool Calling 失败时使用确定性 fallback，因此模型输出不会改变工作流拓扑。

### 3. Milvus Hybrid RAG

当前向量检索集合为 `cs2_tactical_knowledge`，每条文档保留 `map`、`match_id`、`round_number`、`tactic_type`、`parent_id` 和 `parent_content` 等元数据。

一次检索包含以下步骤：

1. LLM 将口语查询改写为 CS2 专业术语查询；LLM 不可用时退回原查询。
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
- Global Search：对多个社区摘要进行全局排序，返回社区摘要及其回合来源 ID；最终综合由 Analyst/Coach 完成。

社区摘要采用确定性抽取式统计，包含回合数、比赛数、击杀、首杀、道具、下包、战术银标、回合胜者和首杀玩家等事实。它不会把少量样本直接表达为“所有职业队都这样打”。

### 5. 前端复盘工作台

`frontend/` 是独立的 React + Vite 应用，采用 `/api` proxy 连接 FastAPI，不复制后端业务逻辑：

- 上传页提交 `.dem` 和 `analysis_mode`，后端返回 Celery `task_id`。
- 前端每两秒轮询 `GET /api/tasks/{task_id}`，在 SUCCESS 后展示 `analysis` 结果。
- Dashboard 展示指标、Agent 执行链、Analyst/Coach 报告、Verifier 状态和 `[E#]` 证据。
- GraphRAG 面板通过只读接口加载地图、节点/边、Global Search、选手画像和战队对比结果。
- 子图使用 SVG 绘制，避免引入大型图可视化依赖；移动端通过 CSS breakpoint 降级为单列布局。

### 6. 可靠性和审核边界

- 指标计算先于 LLM，模型不能伪造缺失的 ADR/KAST。
- Critique 只评价证据相关性和覆盖度，不让模型决定是否“战术正确”。
- Verifier 不调用 LLM，检查未知 `[E#]`、未引用的关键建议和验证状态。
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
MODEL_NAME=qwen-plus

# Milvus 向量数据库
MILVUS_URI="http://localhost:19530"
MILVUS_TOKEN=""

# Celery 消息队列（需要本地运行 Redis）
CELERY_BROKER_URL="redis://localhost:6379/0"
CELERY_RESULT_BACKEND="redis://localhost:6379/1"
```

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

同一个 SQLite 图谱还提供跨比赛分析：选手画像聚合击杀、死亡、助攻、首杀/首死、补枪、道具、下包和六类战术序列参与；战队对比则把战术序列统一换算为每 100 个实际参赛回合，避免不同比赛数量造成总量偏差。战术切片可按地图、T/CT 和对手过滤，并计算首杀后胜率、丢首杀翻盘率、补枪回合胜率、Post-plant、Retake contact 和 Execute candidate 的回合转化，同时列出首杀、补枪和道具协同的选手责任分布。每个结果都保留 `graph:{match}:{map}:{round}` 来源。当前指标是描述性统计，不宣称战术因果；Flash 指标不可用时会在画像方法元数据中明确标记。

### 4. 启动 API 与 Worker

```bash
make dev
```

### 5. 启动前端复盘工作台

另开一个终端执行：

```bash
make frontend-install
make frontend
```

浏览器打开 `http://localhost:5173`。前端提供 Demo 上传、异步进度、指标卡片、Analyst/Coach 报告、证据引用、GraphRAG 子图、Global Search、跨比赛选手画像、五队战术对比和上下文战术切片；Vite 会把 `/api` 请求代理到 `8001`。

新增只读 GraphRAG 展示接口：

```text
GET /api/graph/stats
GET /api/graph/maps
GET /api/graph/search?q=...
GET /api/graph/subgraph?map_name=Mirage
GET /api/graph/players?team=Falcons
GET /api/graph/players/{steamid_or_nickname}
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
│   │   ├── rag_service.py         # RAG：查询重写 + MMR 检索
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
│       ├── prompts.py             # Analyst / Coach 提示词模板
│       ├── workflow.py            # LangGraph 状态机构建 (含 Refine Loop)
│       └── nodes/                 # 受控 Agent 节点与确定性工具节点
│           ├── supervisor_node.py # Supervisor：选择受控分析模式
│           ├── tool_node.py       # Tools：先执行确定性指标计算
│           ├── router_node.py     # Router：元数据抽取 & 过滤信号
│           ├── retrieve_node.py   # Retrieve：向量检索调度
│           ├── critique_node.py   # Critique：检索质量评审 (0.0-1.0)
│           ├── analyst_node.py    # Analyst：HLTV 冷酷数据报告
│           ├── coach_node.py      # Coach：B1ad3 高压战术复盘
│           └── verify_node.py     # Verifier：引用和事实校验
├── scripts/                       # 工具脚本
│   ├── seed_knowledge.py          # Milvus 知识库初始化种子脚本
│   ├── build_graph.py             # GraphRAG 图谱与社区摘要构建
│   ├── evaluate_retrieval.py      # RAG 离线 smoke evaluation
│   ├── fetch_recent_demos.py      # HLTV 职业 Demo 获取入口
│   ├── analyze_local.py           # 本地 Demo 直接分析入口
│   └── test_webhook.py            # Webhook 接口测试脚本
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
> Supervisor 通过白名单 `select_analysis_plan` 工具自主选择四种模式及检索任务；工具调用失败时自动回退到确定性路由。Tools 节点先运行确定性指标计算，LLM 只能解释其结果。

### 📚 Retrieve（战术知识检索器）
> 调用 `KnowledgeBaseClient`：先用 LLM 做查询重写，再通过 Milvus 原生 dense + BM25 混合检索并保留父摘要与证据来源。

知识库默认使用 Milvus 原生 dense + BM25 混合检索，并在证据中保留比赛/地图父摘要；旧的 dense 集合仍可通过 `RAG_HYBRID_ENABLED=false` 走兼容 fallback。使用 `make eval-rag` 运行固定查询的离线 smoke evaluation。

### ⚖️ Critique（检索质量裁判）
> 以苛刻的 CS2 战术法官身份，对检索结果进行结构化质量评审。**评分低于 0.7 时，评审反馈会加入下一轮查询，最多重试三次。**

### ✅ Verifier（事实与引用校验器）
> 不调用 LLM，检查报告中的 `[E#]` 是否存在、是否有未知引用，以及关键建议是否缺少证据标记。

### 🔬 Analyst（HLTV 首席数据师）
> 冷酷客观，只陈述确定性指标和其证据；缺失 ADR、KAST 等原始数据时明确标记 unavailable。**绝对禁止给出主观建议。**

### 🎯 Coach（B1ad3 风格战术执行官）
> 一线职业队教练。根据数据师的报告，使用专业黑话（Exec、Retake、Trading、默认控制权）进行战术推演和复盘。
> *不接受"没坐标、没血量、没语音日志"的汇报。*

### 🔐 知识摄取审核闸门
> 自学习入库默认关闭。只有 `AUTO_INGEST_ENABLED=true`、输入标记 `extra_data.knowledge_approved=true`、来源标记为高质量且 Verifier 通过时，分析任务才会提交入库；否则结果会返回 `knowledge_review.status=pending_review`，可由人工确认后调用手动 `/api/knowledge/ingest`。

### ✅ 本地验证

```bash
make test       # 单元与集成测试
make eval-rag   # 固定查询的 Milvus RAG 评估
make graph-build
make silver-dataset # 生成带置信度与证据来源的战术银标数据集
```

GraphRAG 当前采用确定性抽取式社区摘要；摘要只概括解析到的事实，并保留回合来源，不把小样本观察直接升级为职业战术定律。

`make silver-dataset` 会将本地 Demo 转换为 `datasets/silver/v0.2/` 下的回合级研究数据。v0.2 固定采用 `datasets/selections/five_teams_recent_20_v1.json` 的 20 场近期比赛，共 49 张地图、1,030 回合和 5,325 个战术银标；v0.1 作为单场初始基线保留。首杀和下包阶段来自直接事件事实；补枪、Utility Burst 与 Retake Contact 来自明确的时间窗规则；只有 T 方道具序列后成功下包才会追加弱监督的 Execute Candidate。所有标签都保存规则版本、置信度、审核状态和证据事件 ID。该数据集定位为可复现的 silver labels，不宣称是职业教练人工标注的 gold labels。

---

## 📝 License

MIT © 2026

---

<div align="center">
<sub>Built with ❤️ for the CS2 competitive scene.</sub>
</div>

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
- 驱动五个串行节点（**Router → Retrieve → Critique → Analyst → Coach**）构成一条带有 **Refine Loop 自修复** 的端到端战术推演流水线。
- Critique 节点在检索质量低于阈值时触发 **自动重试回路**，确保送入分析节点的上下文始终达标。
- 以 **HLTV 首席数据师** 的冷酷视角提炼 ADR、KAST、首杀率等核心指标，再通过 **B1ad3 风格教练** 的高压战术复盘进行专业拆解。
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
          │   [Router] ──► [Retrieve] ──► [Critique] ──► [Analyst] ──► [Coach]
          │                    │              │                  │
          │                    │    score<0.7? │                  │
          │                    ◄──── Refine ───┘                  │
          │               PRF重写查询                        HLTV数据报告
          │               MMR+稀疏混合检索                   B1ad3高压复盘
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
| **智能体编排** | LangGraph (StateGraph) | Router → Retrieve → Critique → Analyst → Coach 五节点流水线，含 Refine Loop |
| **高级检索 (RAG)** | LangChain + Milvus | PRF 查询重写 + MMR 多样性召回 + BM25 稀疏检索融合（RRF 混合排序） |
| **LLM** | 阿里云 DashScope / 通义千问 | `qwen-plus` 模型推理（通过 OpenAI 兼容接口接入） |
| **Embedding** | DashScopeEmbeddings | `text-embedding-v2` 向量化 |
| **Demo 解析** | awpy + demoparser2 | CS2 录像帧事件精准提取（击杀链/道具/闪光/下包） |
| **架构规范** | DDD (领域驱动设计) | 高内聚低耦合的 Clean Architecture 目录规范 |

---

## 🚀 快速开始

### 1. 克隆并初始化环境

```bash
git clone https://github.com/Zzz0zzZ0/CS2-coach-agent.git
cd CS2-coach-agent

python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

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

# ChromaDB（仅 seed 脚本使用）
CHROMA_DB_DIR="./chroma_db"
```

### 3. 启动基础设施

确保 **Redis** 和 **Milvus** 服务已运行（推荐使用 Docker）：

```bash
# Redis
docker run -d --name redis -p 6379:6379 redis:latest

# Milvus Standalone
# 参考: https://milvus.io/docs/install_standalone-docker.md
```

### 4. 初始化战术知识向量库

```bash
python scripts/seed_chroma.py
```

> 这一步会向知识库注入涵盖 Mirage / Inferno / Dust2 / Nuke / Ancient 的顶级战术分析片段。

### 5. 启动 Celery Worker

```bash
celery -A app.core.celery_app worker --loglevel=info
```

### 6. 使用方式

**方式 A：直接分析本地 Demo（推荐开发使用）**
```bash
python scripts/analyze_local.py data/your_match.dem
```

**方式 B：启动 Web 服务，接收第三方 Webhook**
```bash
# DDD 架构版（推荐生产使用）
python -m app.main

# 或使用根目录单体入口（Legacy 兼容）
python main.py
```

随后发送 POST 请求到 `http://127.0.0.1:8000/api/webhook/match-end`：

```json
{
  "match_id": "match-001",
  "map_name": "Mirage",
  "rounds": [...]
}
```

或者上传实体录像文件：
```bash
curl -X POST http://127.0.0.1:8000/api/upload-demo \
  -F "file=@data/sample.dem"
```

查询异步任务状态：
```bash
curl http://127.0.0.1:8000/api/tasks/{task_id}
```

---

## 📁 项目结构

```
CS2-coach-agent/
├── app/                           # DDD 架构主应用
│   ├── main.py                    # FastAPI 服务入口点
│   ├── api/                       # 接入层：FastAPI 路由与依赖注入
│   │   ├── dependencies.py        # LLM / Milvus 单例工厂
│   │   └── routers/
│   │       ├── webhooks.py        # POST /api/webhook/match-end
│   │       ├── uploads.py         # POST /api/upload-demo
│   │       └── tasks.py           # GET  /api/tasks/{task_id}
│   ├── core/                      # 核心配置
│   │   ├── config.py              # 环境变量统一管理 (Settings)
│   │   └── celery_app.py          # Celery 应用实例
│   ├── domain/                    # 领域模型
│   │   └── match_models.py        # Pydantic 数据验证 Schema
│   ├── services/                  # 应用服务层
│   │   ├── rag_service.py         # 高级 RAG：PRF 重写 + MMR + 稀疏混合检索
│   │   ├── parser_service.py      # Demo 解析器：demoparser2 封装
│   │   └── tasks.py               # Celery 异步任务定义
│   └── agentic/                   # 智能体编排层
│       ├── states.py              # GraphState 全局状态定义
│       ├── prompts.py             # Analyst / Coach 提示词模板
│       ├── workflow.py            # LangGraph 状态机构建 (含 Refine Loop)
│       └── nodes/                 # 五个智能体节点
│           ├── router_node.py     # Router：元数据抽取 & 过滤信号
│           ├── retrieve_node.py   # Retrieve：向量检索调度
│           ├── critique_node.py   # Critique：检索质量评审 (0.0-1.0)
│           ├── analyst_node.py    # Analyst：HLTV 冷酷数据报告
│           └── coach_node.py      # Coach：B1ad3 高压战术复盘
├── src/                           # Legacy 遗留模块（单体版）
│   ├── data_parser.py             # 早期 Demo 解析器
│   ├── agent_orchestrator.py      # 早期 LangGraph 编排
│   ├── advanced_rag.py            # 早期 RAG 实现
│   └── prompts.py                 # 早期提示词
├── scripts/                       # 工具脚本
│   ├── seed_chroma.py             # 知识库初始化种子脚本
│   ├── analyze_local.py           # 本地 Demo 直接分析入口
│   └── test_webhook.py            # Webhook 接口测试脚本
├── main.py                        # 根目录单体入口（Legacy 兼容）
├── test_main.py                   # 端到端集成测试
├── .env.example                   # 环境变量模板
├── requirements.txt               # Python 依赖
├── data/                          # .dem 录像文件存放（本地，不入库）
└── output/                        # 分析结果输出（日志/JSON，不入库）
```

---

## 🎭 智能体角色设计

### 🧭 Router（元数据抽取器）
> 使用 LLM 从原始赛后数据中智能抽取地图名称等结构化元数据，生成过滤信号供下游 Retrieve 节点使用。**抽取失败时静默退化为全局检索。**

### 📚 Retrieve（战术知识检索器）
> 调用 `KnowledgeBaseClient` 的高级 RAG 管线：先用 LLM 做 PRF 查询重写，再通过 MMR + BM25 稀疏检索的 RRF 混合排序召回最相关的战术知识片段。

### ⚖️ Critique（检索质量裁判）
> 以苛刻的 CS2 战术法官身份，对检索结果进行 0.0-1.0 的质量打分。**当评分低于 0.7 且重试次数未超限时，触发 Refine Loop 回退至 Retrieve 节点重新检索。**

### 🔬 Analyst（HLTV 首席数据师）
> 冷酷客观，仅从数据中提取 ADR、KAST、首杀率等指标。**绝对禁止给出主观建议。**

### 🎯 Coach（B1ad3 风格战术执行官）
> 一线职业队教练。根据数据师的报告，使用专业黑话（Exec、Retake、Trading、默认控制权）进行战术推演和复盘。
> *不接受"没坐标、没血量、没语音日志"的汇报。*

---

## 📝 License

MIT © 2026

---

<div align="center">
<sub>Built with ❤️ for the CS2 competitive scene.</sub>
</div>

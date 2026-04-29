<div align="center">

# 🎯 CS2 Coach Agent
### *由多智能体驱动的 CS2 职业赛事战术复盘系统*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6B35?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-8B5CF6?style=flat-square)](https://www.trychroma.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

---

## 📖 项目简介

**CS2 Coach Agent** 是一个以 **多智能体状态机** 为核心、具备 **高级 RAG 战术检索能力** 的 CS2 职业赛事智能分析系统。

它能够：
- 直接吃入 `.dem` 录像文件，自动解析每一回合的击杀链、道具落点、闪光致盲序列和下包行为。
- 驱动三个串行节点（**Retrieve → Analyst → Coach**）构成一条端到端的战术推演流水线。
- 以 **HLTV 首席数据师** 的冷酷视角提炼 ADR、KAST、首杀率等核心指标，再通过 **B1ad3 风格教练** 的高压战术复盘进行专业拆解。
- 同时支持 **FACEIT / 5E Webhook 数据流** 和 **实体 `.dem` 文件上传** 两种数据接入模式。

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
          │           LangGraph 多智能体状态机 (Agentic Workflow)│
          │                                                      │
          │   [Router] ──► [Retrieve] ──► [Critique] ──► [Analyst] ──► [Coach]
          │                  │                                   │
          │             PRF重写查询                         HLTV数据报告
          │             MMR多样性召回                       B1ad3高压复盘
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
| **Web 层** | FastAPI + Uvicorn | 异步 Webhook 服务，支持 `.dem` 文件上传及任务查询 |
| **异步队列** | Celery + Redis | 企业级后台耗时任务队列，实现系统高并发与横向扩展 |
| **智能体编排** | LangGraph (StateGraph) | Router → Retrieve → Critique → Analyst → Coach 五节点流水线 |
| **高级检索 (RAG)**| LangChain + Milvus | PRF 查询重写 + MMR 多样性召回（支持亿级并发检索） |
| **LLM** | 阿里云 DashScope / 通义千问 | `qwen-plus` 模型推理与情感/状态评估 |
| **Embedding** | DashScopeEmbeddings | `text-embedding-v2` 向量化 |
| **Demo 解析** | awpy + demoparser2 | CS2 录像帧事件精准提取 |
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

编辑 `.env`，填入你的阿里云 DashScope API Key：

```env
DASHSCOPE_API_KEY="sk-your-key-here"
MODEL_NAME=qwen-plus-2025-07-28
CHROMA_DB_DIR="./chroma_db"
```

### 3. 初始化战术知识向量库

```bash
python scripts/seed_chroma.py
```

> 这一步会向本地 ChromaDB 注入 5 段涵盖 Mirage / Inferno / Dust2 / Nuke / Ancient 的顶级战术分析片段。

### 4. 使用方式

**方式 A：直接分析本地 Demo（推荐开发使用）**
```bash
python scripts/analyze_local.py data/your_match.dem
```

**方式 B：启动 Web 服务，接收第三方 Webhook**
```bash
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

---

## 📁 项目结构

```
CS2-coach-agent/
├── app/
│   ├── api/                   # 接入层：FastAPI 路由与依赖注入
│   │   ├── dependencies.py
│   │   └── routers/
│   ├── core/                  # 核心配置：环境变量与 Celery 应用
│   │   ├── config.py
│   │   └── celery_app.py
│   ├── domain/                # 领域模型：Pydantic 数据验证
│   │   └── match_models.py
│   ├── services/              # 应用服务层：RAG 与数据解析
│   │   ├── rag_service.py     # 封装 Milvus 混合检索
│   │   ├── parser_service.py  # 封装 demoparser2
│   │   └── tasks.py           # Celery 异步任务定义
│   ├── agentic/               # 智能体编排层：LangGraph 节点
│   │   ├── nodes/             # Router, Retrieve, Analyst, Coach, Critique
│   │   ├── prompts.py
│   │   ├── states.py
│   │   └── workflow.py
│   └── main.py                # 服务入口点
├── test_main.py               # 端到端集成测试脚本
├── .env.example               # 环境变量模板
├── requirements.txt           # Python 依赖
└── data/                      # 放置 .dem 录像文件 (本地，不入库)
```

---

## 🎭 智能体角色设计

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

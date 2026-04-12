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
          │              FastAPI Web Service (main.py)          │
          │                                                     │
          │   POST /api/webhook/match-end  (JSON Payload)       │
          │   POST /api/upload-demo        (.dem 实体文件上传)  │
          └──────────────────────┬──────────────────────────────┘
                                 │ BackgroundTasks (非阻塞)
                                 ▼
          ┌──────────────────────────────────────────────────────┐
          │           LangGraph 多智能体状态机                   │
          │                                                      │
          │   [node_retrieve] ──► [node_analyst] ──► [node_coach]│
          │        │                    │                  │     │
          │   PRF重写查询           HLTV数据报告        B1ad3复盘│
          │   MMR多样性召回         ADR/KAST/首杀率    战术裁决  │
          └──────────────────────────────────────────────────────┘
                │                       ▲
                ▼                       │
          ┌──────────┐          ┌───────────────┐
          │ ChromaDB │          │ DashScope LLM │
          │ 向量知识库│          │ (通义千问)    │
          └──────────┘          └───────────────┘
                ▲
                │ seed_chroma.py
          ┌──────────────────┐
          │ CS2 战术知识片段  │
          │ (5张地图专业文本) │
          └──────────────────┘
```

---

## ⚡ 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **Web 层** | FastAPI + Uvicorn | 异步 Webhook 服务，支持 `.dem` 文件上传 |
| **智能体编排** | LangGraph (StateGraph) | Retrieve → Analyst → Coach 三节点流水线 |
| **高级检索 (RAG)** | LangChain + ChromaDB | PRF 查询重写 + MMR 多样性召回 |
| **LLM** | 阿里云 DashScope / 通义千问 | `qwen-plus` 模型推理 |
| **Embedding** | DashScopeEmbeddings | `text-embedding-v2` 向量化 |
| **Demo 解析** | awpy + demoparser2 | CS2 录像帧事件精准提取 |
| **数据验证** | Pydantic v2 | 严格的 Webhook Payload 校验 |

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
├── main.py                    # FastAPI 服务入口 (Webhook + 文件上传)
├── .env.example               # 环境变量模板
├── requirements.txt           # Python 依赖
├── src/
│   ├── data_parser.py         # CS2 Demo 解析器 (TacticalDemoParser)
│   ├── advanced_rag.py        # PRF 查询重写 + MMR 检索 (TacticalRetriever)
│   ├── agent_orchestrator.py  # LangGraph 状态机与节点定义
│   └── prompts.py             # ANALYST_PROMPT & COACH_PROMPT
├── scripts/
│   ├── analyze_local.py       # 本地一键分析 CLI
│   ├── seed_chroma.py         # 向量知识库初始化
│   └── test_webhook.py        # 端到端 Webhook 集成测试
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

<div align="center">

# 🎯 CS2 Coach Agent
### *A Multi-Agent Driven CS2 Professional Match Tactical Analysis System*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6B35?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-8B5CF6?style=flat-square)](https://www.trychroma.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

---

## 📖 Overview

**CS2 Coach Agent** is an intelligent CS2 professional match analysis system built on a **multi-agent state machine** core with **advanced RAG tactical retrieval** capabilities.

It can:
- Ingest `.dem` demo files directly, automatically parsing kill chains, grenade landing positions, flash-blind sequences, and bomb plant events for every round.
- Drive three serial nodes (**Retrieve → Analyst → Coach**) to form an end-to-end tactical inference pipeline.
- Extract core metrics such as ADR, KAST, and first-kill rate from an **HLTV Chief Data Analyst** perspective, then deliver a high-pressure tactical breakdown through a **B1ad3-style Coach**.
- Support both **FACEIT / 5E Webhook data streams** and **direct `.dem` file uploads** as data ingestion modes.

---

## 🏗️ System Architecture

```
          ┌─────────────────────────────────────────────────────┐
          │              FastAPI Web Service (app/main.py)      │
          │                                                     │
          │   POST /api/webhook/match-end  (JSON Payload)       │
          │   POST /api/upload-demo        (.dem file upload)   │
          │   GET  /api/tasks/{task_id}    (Task status query)  │
          └──────────────────────┬──────────────────────────────┘
                                 │ Celery task.delay() Push
                                 ▼
                          ┌────────────┐
                          │  Redis MQ  │
                          └──────┬─────┘
                                 │ Dispatch to Celery Worker
                                 ▼
          ┌──────────────────────────────────────────────────────┐
          │         LangGraph Multi-Agent State Machine          │
          │                                                      │
          │   [Router] ──► [Retrieve] ──► [Critique] ──► [Analyst] ──► [Coach]
          │                  │                                   │
          │             PRF Query Rewrite                   HLTV Data Report
          │             MMR Diverse Recall                  B1ad3 Review
          └──────────────────────────────────────────────────────┘
                 │                       ▲
                 ▼                       │
          ┌──────────┐          ┌───────────────┐
          │  Milvus  │          │ DashScope LLM │
          │ Vector DB│          │ (Qwen)        │
          └──────────┘          └───────────────┘
```

---

## ⚡ Tech Stack

| Layer | Technology | Description |
|-------|-----------|-------------|
| **Web Layer** | FastAPI + Uvicorn | Async Webhook service, supporting `.dem` uploads and task queries |
| **Async Queue** | Celery + Redis | Enterprise background task queue for high concurrency & scale-out |
| **Agent Orchestration** | LangGraph (StateGraph) | Router → Retrieve → Critique → Analyst → Coach five-node pipeline |
| **Advanced Retrieval (RAG)** | LangChain + Milvus | PRF query rewriting + MMR diversity recall (Billion-scale support) |
| **LLM** | Alibaba Cloud DashScope / Qwen | `qwen-plus` model inference & emotion/status evaluation |
| **Embedding** | DashScopeEmbeddings | `text-embedding-v2` vectorization |
| **Demo Parsing** | awpy + demoparser2 | Precise CS2 demo frame event extraction |
| **Architecture** | DDD (Domain-Driven Design) | High cohesion, low coupling Clean Architecture pattern |

---

## 🚀 Quick Start

### 1. Clone and Initialize Environment

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

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your Alibaba Cloud DashScope API Key:

```env
DASHSCOPE_API_KEY="sk-your-key-here"
MODEL_NAME=qwen-plus-2025-07-28
CHROMA_DB_DIR="./chroma_db"
```

### 3. Initialize the Tactical Knowledge Vector Store

```bash
python scripts/seed_chroma.py
```

> This step injects 5 professional tactical analysis documents covering Mirage / Inferno / Dust2 / Nuke / Ancient into the local ChromaDB.

### 4. Usage

**Option A: Analyze a local Demo directly (recommended for development)**
```bash
python scripts/analyze_local.py data/your_match.dem
```

**Option B: Start the Web service to receive third-party Webhooks**
```bash
python main.py
```

Then send a POST request to `http://127.0.0.1:8000/api/webhook/match-end`:

```json
{
  "match_id": "match-001",
  "map_name": "Mirage",
  "rounds": [...]
}
```

Or upload a demo file directly:
```bash
curl -X POST http://127.0.0.1:8000/api/upload-demo \
  -F "file=@data/sample.dem"
```

---

## 📁 Project Structure

```
CS2-coach-agent/
├── app/
│   ├── api/                   # API Layer: FastAPI routers & dependency injection
│   │   ├── dependencies.py
│   │   └── routers/
│   ├── core/                  # Core config: Env variables & Celery app
│   │   ├── config.py
│   │   └── celery_app.py
│   ├── domain/                # Domain models: Pydantic schemas
│   │   └── match_models.py
│   ├── services/              # Application Services: RAG and Demo Parsing
│   │   ├── rag_service.py     # Milvus hybrid search integration
│   │   ├── parser_service.py  # demoparser2 wrapper
│   │   └── tasks.py           # Celery async tasks definitions
│   ├── agentic/               # Agent Orchestration: LangGraph
│   │   ├── nodes/             # Router, Retrieve, Analyst, Coach, Critique
│   │   ├── prompts.py
│   │   ├── states.py
│   │   └── workflow.py
│   └── main.py                # Service entry point
├── test_main.py               # End-to-end integration test script
├── .env.example               # Environment variable template
├── requirements.txt           # Python dependencies
└── data/                      # Place .dem demo files here (local only, not committed)
```

---

## 🎭 Agent Role Design

### 🔬 Analyst (HLTV Chief Data Analyst)
> Cold and objective. Extracts only ADR, KAST, first-kill rate, and other metrics from raw data. **Subjective recommendations are strictly forbidden.**

### 🎯 Coach (B1ad3-Style Tactical Enforcer)
> A frontline professional team coach. Uses professional jargon (Exec, Retake, Trading, Default Control) to conduct tactical deductions and debriefs based on the Analyst's report.
> *Does not accept reports without coordinates, health values, or voice logs.*

---

## 📝 License

MIT © 2026

---

<div align="center">
<sub>Built with ❤️ for the CS2 competitive scene.</sub>
</div>

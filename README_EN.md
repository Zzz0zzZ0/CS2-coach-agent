<div align="center">

# 🎯 CS2 Coach Agent
### *A Multi-Agent Driven CS2 Professional Match Tactical Analysis System*

[中文文档](README.md)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-FF6B35?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Milvus](https://img.shields.io/badge/Milvus-VectorDB-00A1EA?style=flat-square)](https://milvus.io/)
[![Celery](https://img.shields.io/badge/Celery-Redis-37814A?style=flat-square&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

---

## 📖 Overview

**CS2 Coach Agent** is an intelligent CS2 professional match analysis system built on a **multi-agent state machine** core with **advanced RAG tactical retrieval** capabilities.

It can:
- Ingest `.dem` demo files directly, leveraging `demoparser2` to automatically parse kill chains, grenade landing positions, flash-blind sequences, and bomb plant events for every round.
- Drive five serial nodes (**Router → Retrieve → Critique → Analyst → Coach**) to form an end-to-end tactical inference pipeline with a built-in **Refine Loop for self-healing**.
- The Critique node triggers an **automatic retry loop** when retrieval quality falls below a threshold, ensuring the context fed into the Analyst is always up to standard.
- Extract core metrics such as ADR, KAST, and first-kill rate from an **HLTV Chief Data Analyst** perspective, then deliver a high-pressure tactical breakdown through a **B1ad3-style Coach**.
- Support both **FACEIT / 5E Webhook data streams** and **direct `.dem` file uploads** as data ingestion modes.
- All heavy tasks are processed through a **Celery + Redis** async message queue, supporting high concurrency and horizontal scaling.

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
          │        LangGraph Multi-Agent State Machine           │
          │                                                      │
          │   [Router] ──► [Retrieve] ──► [Critique] ──► [Analyst] ──► [Coach]
          │                    │              │                  │
          │                    │    score<0.7? │                  │
          │                    ◄──── Refine ───┘                  │
          │               PRF Query Rewrite                 HLTV Data Report
          │               MMR+Sparse Hybrid                 B1ad3 Review
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
| **Web Layer** | FastAPI + Uvicorn | Async Webhook service, supporting `.dem` uploads and task status queries |
| **Async Queue** | Celery + Redis | Enterprise background task queue for high concurrency & horizontal scaling |
| **Agent Orchestration** | LangGraph (StateGraph) | Router → Retrieve → Critique → Analyst → Coach five-node pipeline with Refine Loop |
| **Advanced Retrieval (RAG)** | LangChain + Milvus | PRF query rewriting + MMR diversity recall + BM25 sparse retrieval fusion (RRF hybrid ranking) |
| **LLM** | Alibaba Cloud DashScope / Qwen | `qwen-plus` model inference (via OpenAI-compatible API) |
| **Embedding** | DashScopeEmbeddings | `text-embedding-v2` vectorization |
| **Demo Parsing** | awpy + demoparser2 | Precise CS2 demo frame event extraction (kills/grenades/flashes/plants) |
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

Edit `.env` and fill in your Alibaba Cloud DashScope API Key and infrastructure config:

```env
# DashScope / OpenAI-compatible API
DASHSCOPE_API_KEY="sk-your-key-here"
MODEL_NAME=qwen-plus

# Milvus Vector Database
MILVUS_URI="http://localhost:19530"
MILVUS_TOKEN=""

# Celery Message Queue (requires local Redis)
CELERY_BROKER_URL="redis://localhost:6379/0"
CELERY_RESULT_BACKEND="redis://localhost:6379/1"

# ChromaDB (used by seed script only)
CHROMA_DB_DIR="./chroma_db"
```

### 3. Start Infrastructure

Ensure **Redis** and **Milvus** are running (Docker recommended):

```bash
# Redis
docker run -d --name redis -p 6379:6379 redis:latest

# Milvus Standalone
# See: https://milvus.io/docs/install_standalone-docker.md
```

### 4. Initialize the Tactical Knowledge Vector Store

```bash
python scripts/seed_chroma.py
```

> This step injects professional tactical analysis documents covering Mirage / Inferno / Dust2 / Nuke / Ancient into the knowledge base.

### 5. Start Celery Worker

```bash
celery -A app.core.celery_app worker --loglevel=info
```

### 6. Usage

**Option A: Analyze a local Demo directly (recommended for development)**
```bash
python scripts/analyze_local.py data/your_match.dem
```

**Option B: Start the Web service to receive third-party Webhooks**
```bash
# DDD architecture version (recommended for production)
python -m app.main

# Or use the root monolithic entry (Legacy compatible)
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

Query async task status:
```bash
curl http://127.0.0.1:8000/api/tasks/{task_id}
```

---

## 📁 Project Structure

```
CS2-coach-agent/
├── app/                           # DDD Architecture Main Application
│   ├── main.py                    # FastAPI service entry point
│   ├── api/                       # API Layer: FastAPI routers & dependency injection
│   │   ├── dependencies.py        # LLM / Milvus singleton factory
│   │   └── routers/
│   │       ├── webhooks.py        # POST /api/webhook/match-end
│   │       ├── uploads.py         # POST /api/upload-demo
│   │       └── tasks.py           # GET  /api/tasks/{task_id}
│   ├── core/                      # Core Configuration
│   │   ├── config.py              # Centralized env variable management (Settings)
│   │   └── celery_app.py          # Celery application instance
│   ├── domain/                    # Domain Models
│   │   └── match_models.py        # Pydantic validation schemas
│   ├── services/                  # Application Services
│   │   ├── rag_service.py         # Advanced RAG: PRF rewrite + MMR + sparse hybrid search
│   │   ├── parser_service.py      # Demo parser: demoparser2 wrapper
│   │   └── tasks.py               # Celery async task definitions
│   └── agentic/                   # Agent Orchestration Layer
│       ├── states.py              # GraphState global state definition
│       ├── prompts.py             # Analyst / Coach prompt templates
│       ├── workflow.py            # LangGraph state machine builder (with Refine Loop)
│       └── nodes/                 # Five agent nodes
│           ├── router_node.py     # Router: metadata extraction & filter signal
│           ├── retrieve_node.py   # Retrieve: vector search dispatch
│           ├── critique_node.py   # Critique: retrieval quality review (0.0-1.0)
│           ├── analyst_node.py    # Analyst: HLTV cold data report
│           └── coach_node.py      # Coach: B1ad3 tactical debrief
├── src/                           # Legacy Modules (monolithic version)
│   ├── data_parser.py             # Early demo parser
│   ├── agent_orchestrator.py      # Early LangGraph orchestration
│   ├── advanced_rag.py            # Early RAG implementation
│   └── prompts.py                 # Early prompt templates
├── scripts/                       # Utility Scripts
│   ├── seed_chroma.py             # Knowledge base seed script
│   ├── analyze_local.py           # Local demo direct analysis entry
│   └── test_webhook.py            # Webhook API test script
├── main.py                        # Root monolithic entry (Legacy compatible)
├── test_main.py                   # End-to-end integration test
├── .env.example                   # Environment variable template
├── requirements.txt               # Python dependencies
├── data/                          # .dem demo files (local only, not committed)
└── output/                        # Analysis results output (logs/JSON, not committed)
```

---

## 🎭 Agent Role Design

### 🧭 Router (Metadata Extractor)
> Uses LLM to intelligently extract structured metadata like map names from raw post-match data, generating filter signals for the downstream Retrieve node. **Silently degrades to global search on extraction failure.**

### 📚 Retrieve (Tactical Knowledge Retriever)
> Invokes the `KnowledgeBaseClient` advanced RAG pipeline: first uses LLM for PRF query rewriting, then performs RRF hybrid ranking through MMR + BM25 sparse retrieval to recall the most relevant tactical knowledge fragments.

### ⚖️ Critique (Retrieval Quality Judge)
> Acts as a demanding CS2 tactical judge, scoring retrieval results on a 0.0-1.0 scale. **When the score falls below 0.7 and retry count hasn't exceeded the limit, triggers a Refine Loop back to the Retrieve node for re-retrieval.**

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

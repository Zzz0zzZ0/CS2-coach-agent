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
- Built-in **HLTV data scraper and demo downloader**, supporting automated acquisition of high-value professional match Demo datasets.
- Drive **Supervisor (bounded tool calling) → Tools → Router → parallel task retrieval → Critique → Analyst → Coach → Verifier** with a feedback-based **Refine Loop**; knowledge ingestion requires verification, explicit approval, and a configuration switch.
- The Critique node triggers a **feedback-based retry loop** when retrieval quality falls below a threshold; after the maximum attempts it preserves the low-quality signal instead of pretending the context passed.
- Compute verifiable kill, first-kill, and round metrics in code first, then use an **HLTV Chief Data Analyst** and **B1ad3-style Coach** for reporting and tactical review; unavailable data is never fabricated as ADR/KAST.
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
          │   [Supervisor] ──► [Tools] ──► [Router] ──► [Task Retrieval] ──► [Critique] ──► [Analyst] ──► [Coach] ──► [Verifier]
          │                    │                    │                  │
          │                    │       missing task? │                  │
          │                    ◄──── Refine only failed tasks             │
          │               opening/utility/round/map tasks          citation and fact checks
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
| **Agent Orchestration** | LangGraph (StateGraph) | Bounded tool calling → deterministic tools → parallel retrieval → rule/LLM review → analysis → coaching → citation verification |
| **Retrieval (RAG)** | Milvus 2.6 + LangChain | Dense + native BM25 hybrid retrieval, RRF, parent context, corrective retrieval, and evidence tracing |
| **LLM** | Alibaba Cloud DashScope / Qwen | `qwen-plus` model inference (via OpenAI-compatible API) |
| **Embedding** | FastEmbed + ONNX | Local multilingual embeddings without DashScope embedding usage |
| **Data Acquisition**| DrissionPage | HLTV match data scraping and automated `.dem` downloads |
| **Demo Parsing** | awpy + demoparser2 | Precise CS2 demo frame event extraction (kills/grenades/flashes/plants) |
| **Architecture** | DDD (Domain-Driven Design) | High cohesion, low coupling Clean Architecture pattern |

---

## 🔬 Technical Implementation Details

### 1. Data Flow: Demo to Coaching Advice

```text
.dem / Webhook JSON
        │
        ▼
TacticalDemoParser
        │  round_end / player_death / grenade / flash / bomb events
        ▼
Structured MatchWebhookPayload
        │
        ├── Tools: deterministic metrics
        ├── Milvus: hybrid text retrieval
        ├── GraphRAG: relationship paths and community summaries
        │
        ▼
Critique: task coverage, map match, evidence count and relevance
        │  retry only missing tasks, up to three attempts
        ▼
Analyst: facts only
        ▼
Coach: evidence-bound tactical advice
        ▼
Verifier: [E#] citation and unsupported-claim checks
```

The parser stores observable events and does not directly infer that a utility caused a round win. Causal interpretation is left to Analyst/Coach and must remain tied to evidence, keeping raw facts, model interpretation, and coaching recommendations separate.

### 2. LangGraph State Machine and Bounded Agents

All nodes communicate through `GraphState`. Important fields include:

| Field | Purpose |
|-------|---------|
| `metrics` | Code-computed round, kill, first-kill, and player metrics |
| `analysis_plan` | Router tasks for opening, utility, round flow, and map context |
| `retrieval_task_results` | Per-task coverage, source counts, and warnings |
| `retrieval_evidence` | Traceable evidence normalized into `[E#]` citations |
| `agent_trace` / `tool_trace` | Execution trace shown by the frontend |
| `verification_report` | Unknown citations, missing citations, and review status |

The Supervisor may choose an analysis mode through an allowlisted tool, but cannot create graph nodes, execute code, access the network, or write to the knowledge base. Unsupported or failed tool calls use a deterministic fallback, so model output cannot change the workflow topology.

### 3. Milvus Hybrid RAG

The vector collection is `cs2_tactical_knowledge`. Each document keeps `map`, `match_id`, `round_number`, `tactic_type`, `parent_id`, and `parent_content` metadata.

Each retrieval follows this sequence:

1. Rewrite the natural-language query into CS2 terminology; fall back to the original query when the LLM is unavailable.
2. Generate a 384-dimensional dense embedding locally with FastEmbed/ONNX, avoiding paid embedding API usage.
3. Run native Milvus BM25 sparse retrieval and merge dense/sparse results with RRF.
4. Retrieve original, rewritten, and task-variant queries, then rerank using lexical overlap, rank, and parent-context bonus.
5. Deduplicate with stable evidence keys and reserve a small slice for every task so one topic cannot consume the whole context window.
6. Let Critique retry only uncovered tasks instead of repeating successful retrieval work.

If Milvus is unavailable, the workflow can continue with GraphRAG factual paths; if the GraphRAG database is absent, it falls back to Milvus.

### 4. Two-Level GraphRAG Retrieval

GraphRAG uses a standard-library SQLite sidecar and does not replace Milvus:

```text
nodes:
  match → map → round ┬→ event → player
                      └→ tactical_sequence → event/player

edges:
  HAS_MAP / HAS_ROUND / KILL / USES_UTILITY /
  FLASH_BLIND / PLANTS_BOMB / KILLER / VICTIM /
  HAS_TACTICAL_SEQUENCE / SUPPORTED_BY / INVOLVES_PLAYER
```

- Local Search filters rounds by map, task, and keywords, then returns event paths plus `round → tactical_sequence → evidence/player` paths.
- Community Summary aggregates rounds by “map × topic”; topics currently include overview, opening, utility, and round_flow.
- Global Search ranks multiple community summaries and returns their round source IDs; Analyst/Coach performs the final cross-community synthesis.

Community summaries are deterministic and extractive. They report observed rounds, matches, kills, first kills, utilities, plants, tactical silver labels, winners, and opening players; they do not promote a small sample into a universal professional tactic.

### 5. Frontend Review Console

`frontend/` is an independent React + Vite application that uses the `/api` proxy and does not duplicate backend business logic:

- The upload form submits a `.dem` and `analysis_mode`; the backend returns a Celery `task_id`.
- The console polls `GET /api/tasks/{task_id}` every two seconds and renders the `analysis` payload after SUCCESS.
- The dashboard shows metrics, the Agent execution chain, Analyst/Coach reports, Verifier status, and `[E#]` evidence.
- The GraphRAG panel loads maps, nodes/edges, Global Search, player profiles, and team comparisons through read-only endpoints.
- The subgraph is drawn with SVG instead of a large visualization dependency; CSS breakpoints collapse the layout on mobile.

### 6. Reliability and Review Boundaries

- Deterministic metrics run before any LLM call; missing ADR/KAST cannot be fabricated.
- Critique evaluates evidence relevance and coverage, not whether the model agrees with a tactic.
- Verifier is LLM-free and checks unknown `[E#]` citations, unsupported key recommendations, and verification status.
- Automatic knowledge ingestion is disabled by default and requires a high-quality source, explicit human approval, and a passing Verifier.
- Demos, parsed outputs, the SQLite graph, Milvus volumes, and `.env` are local runtime data and are excluded from Git.

---

## 🚀 Quick Start

### 1. Clone and Initialize Environment

```bash
git clone https://github.com/Zzz0zzZ0/CS2-coach-agent.git
cd CS2-coach-agent
make bootstrap
```

`make bootstrap` creates the Python 3.11 virtual environment, installs runtime/development dependencies, and starts the Redis/Milvus infrastructure.

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
```

### 3. Initialize the Tactical Knowledge Vector Store

```bash
python scripts/seed_knowledge.py
```

> This reads `data/demos/*.dem`, builds structured documents for match summaries, opening-duel evidence, and round events, then replaces the old seed documents in `cs2_tactical_knowledge`. Run `python scripts/seed_knowledge.py --dry-run` first to inspect the document count.

### GraphRAG sidecar

Build the deterministic local graph from parsed Demo events:

```bash
make graph-build
```

The sidecar uses SQLite for match, map, round, event, player, and tactical-sequence relationships. `make graph-build` recomputes the current silver labels and connects each sequence to its source events and participants. Local hits carry `label_source` and confidence into the existing Analyst, Coach, and Verifier `[E#]` contract; `weak_rule` remains a candidate rather than a human-confirmed tactic. If the graph database is absent, the workflow falls back to Milvus only.

The same SQLite graph now powers cross-match analytics. Player profiles aggregate kills, deaths, assists, opening duels, trades, utility, plants, and participation in all six tactical sequence types. Team comparison normalizes every sequence to 100 observed team rounds so unequal match counts do not distort totals. Tactical slices filter by map, T/CT side, and opponent, then calculate round conversion after opening wins/losses, trade rounds, post-plants, retake contacts, and execute candidates. They also expose player responsibility shares for openings, trades, and utility bursts. Each result retains `graph:{match}:{map}:{round}` sources. These are descriptive metrics, not causal claims; profile methodology metadata explicitly flags unavailable flash-event coverage.

### 4. Start the API and Worker

```bash
make dev
```

### 5. Start the Frontend Review Console

In a second terminal:

```bash
make frontend-install
make frontend
```

Open `http://localhost:5173`. The console provides Demo upload, async progress, metric cards, Analyst/Coach reports, evidence citations, a GraphRAG subgraph, Global Search, cross-match player profiles, five-team tactical comparison, and contextual tactical slices. Vite proxies `/api` requests to port `8001`.

Read-only GraphRAG display endpoints:

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

### 6. Usage

**Option A: Analyze a local Demo directly (recommended for development)**
```bash
make analyze DEMO=data/your_match.dem
```

**Option B: Fetch recent professional match Demos**

By default, the scraper queries completed matches from the last 7 days with at least 2 HLTV stars and an explicitly available Demo. If that window has no usable Demos, it widens to the last 30 days and writes match manifests to `data/demos/manifests/`.

```bash
# Discover matches only; do not download large archives
make fetch-demos ARGS="--days 7 --min-rating 2 --max-matches 10"

# Download and extract .dem files (requires unar, 7z, unrar, or bsdtar)
make fetch-demos ARGS="--days 30 --min-rating 2 --max-matches 10 --download"

# Download a reviewed fixed selection for reproducible experiments
make fetch-demos ARGS="--selection-file datasets/selections/five_teams_recent_20_v1.json --download"
```

The downloader only follows an official Demo link exposed on the HLTV match page. It stores a per-match manifest, skips an existing manifest by default, and requires `--force` to download that match again.

**Option C: Start the Web service to receive third-party Webhooks**
```bash
make dev
```

Then send a POST request to `http://127.0.0.1:8001/api/webhook/match-end`:

```json
{
  "match_id": "match-001",
  "map_name": "Mirage",
  "rounds": [...]
}
```

Or upload a demo file directly:
```bash
curl -X POST http://127.0.0.1:8001/api/upload-demo \
  -F "file=@data/sample.dem"
```

Query async task status:
```bash
curl http://127.0.0.1:8001/api/tasks/{task_id}
```

---

## 📁 Project Structure

```
CS2-coach-agent/
├── app/                           # DDD Architecture Main Application
│   ├── main.py                    # FastAPI service entry point
│   ├── api/                       # API Layer: FastAPI routers & dependency injection
│   │   ├── dependencies.py        # FastAPI compatibility exports
│   │   └── routers/
│   │       ├── webhooks.py        # POST /api/webhook/match-end
│   │       ├── uploads.py         # POST /api/upload-demo
│   │       ├── graph.py           # GET  /api/graph/*
│   │       └── tasks.py           # GET  /api/tasks/{task_id}
│   ├── core/                      # Core Configuration
│   │   ├── config.py              # Centralized env variable management (Settings)
│   │   ├── providers.py           # LLM / Milvus providers
│   │   └── celery_app.py          # Celery application instance
│   ├── domain/                    # Domain Models
│   │   ├── match_models.py        # Pydantic validation schemas
│   │   └── analysis_models.py     # Metrics and analysis result models
│   ├── services/                  # Application Services
│   │   ├── rag_service.py         # RAG: query rewrite + MMR retrieval
│   │   ├── graph_rag_service.py    # GraphRAG: graph, communities, Global Search
│   │   ├── metrics_service.py     # Deterministic match metrics
│   │   ├── analysis_pipeline.py   # Unified analysis entry point
│   │   ├── parser_service.py      # Demo parser: demoparser2 wrapper
│   │   └── tasks.py               # Celery async task definitions
│   ├── scrapers/                  # Data Acquisition Layer
│   │   ├── hltv_scraper.py        # HLTV match metadata scraper
│   │   └── demo_downloader.py     # Professional demo automated downloader
│   └── agentic/                   # Agent Orchestration Layer
│       ├── states.py              # GraphState global state definition
│       ├── prompts.py             # Analyst / Coach prompt templates
│       ├── workflow.py            # LangGraph state machine builder (with Refine Loop)
│       └── nodes/                 # Controlled agent and deterministic tool nodes
│           ├── supervisor_node.py # Supervisor: bounded analysis modes
│           ├── tool_node.py       # Tools: deterministic metrics first
│           ├── router_node.py     # Router: metadata extraction & filter signal
│           ├── retrieve_node.py   # Retrieve: vector search dispatch
│           ├── critique_node.py   # Critique: retrieval quality review (0.0-1.0)
│           ├── analyst_node.py    # Analyst: HLTV cold data report
│           ├── coach_node.py      # Coach: B1ad3 tactical debrief
│           └── verify_node.py     # Verifier: citation and fact checks
├── scripts/                       # Utility Scripts
│   ├── seed_knowledge.py          # Milvus knowledge base seed script
│   ├── build_graph.py             # Build GraphRAG graph and communities
│   ├── evaluate_retrieval.py      # Offline RAG smoke evaluation
│   ├── fetch_recent_demos.py      # HLTV professional Demo fetch entrypoint
│   ├── analyze_local.py           # Local demo direct analysis entry
│   └── test_webhook.py            # Webhook API test script
├── test_main.py                   # End-to-end integration test
├── test_agentic.py                # Agent orchestration and tool tests
├── test_graph_rag.py              # GraphRAG path and Global Search tests
├── .env.example                   # Environment variable template
├── Makefile                        # Simplified development entry points
├── requirements.txt               # Python dependencies
├── requirements-dev.txt            # Development and test dependencies
├── frontend/                       # React + Vite review console
│   ├── src/main.jsx                # Dashboard and GraphRAG UI
│   ├── src/api.js                  # Backend request helpers
│   └── src/styles.css              # Dark tactical console styling
├── data/                          # .dem demo files (local only, not committed)
└── output/                        # Analysis results output (logs/JSON, not committed)
```

---

## 🎭 Agent Role Design

### 🧭 Router (Metadata Extractor)
> Uses normalized match metadata to generate retrieval filters, avoiding a redundant LLM extraction step.

### 🧠 Supervisor / Tools (Controlled Orchestration and Tool Layer)
> Supervisor uses the allowlisted `select_analysis_plan` tool to autonomously choose an analysis mode and retrieval tasks. Failed or unsupported tool calls fall back to deterministic routing. Tools computes deterministic metrics before any LLM reasoning.

### 📚 Retrieve (Tactical Knowledge Retriever)
> Invokes `KnowledgeBaseClient` for LLM query rewriting followed by Milvus native dense + BM25 hybrid retrieval with parent context and evidence provenance.

The knowledge base defaults to Milvus native dense + BM25 hybrid retrieval and preserves match/map parent summaries with each evidence hit. Set `RAG_HYBRID_ENABLED=false` for the legacy dense fallback. Run `make eval-rag` for the fixed-query retrieval smoke evaluation.

### ⚖️ Critique (Retrieval Quality Judge)
> Acts as a demanding CS2 tactical judge and returns structured retrieval feedback. **When the score falls below 0.7, that feedback is added to the next query, with up to three attempts.**

### ✅ Verifier (Fact and Citation Checker)
> Uses no LLM. It checks that `[E#]` citations exist, rejects unknown evidence IDs, and flags key recommendations without evidence markers.

### 🔬 Analyst (HLTV Chief Data Analyst)
> Cold and objective. Reports deterministic metrics and evidence; marks ADR, KAST, and other unavailable metrics as unavailable. **Subjective recommendations are strictly forbidden.**

### 🎯 Coach (B1ad3-Style Tactical Enforcer)
> A frontline professional team coach. Uses professional jargon (Exec, Retake, Trading, Default Control) to conduct tactical deductions and debriefs based on the Analyst's report.
> *Does not accept reports without coordinates, health values, or voice logs.*

### 🔐 Knowledge Ingestion Review Gate
> Self-learning ingestion is disabled by default. It runs only when `AUTO_INGEST_ENABLED=true`, `extra_data.knowledge_approved=true`, the source is marked high quality, and Verifier passes. Otherwise the result is returned as `knowledge_review.status=pending_review`; an operator can review it and submit it through `/api/knowledge/ingest`.

### ✅ Local Validation

```bash
make test       # Unit and integration tests
make eval-rag   # Fixed-query Milvus RAG evaluation
make graph-build
make silver-dataset # build evidence-linked tactical silver annotations
```

Community summaries are currently deterministic and extractive: they summarize parsed facts, preserve round-level sources, and do not promote small-sample observations into universal professional tactics.

`make silver-dataset` writes round-level research data to `datasets/silver/v0.2/`. v0.2 uses the fixed 20-match selection in `datasets/selections/five_teams_recent_20_v1.json`, covering 49 maps, 1,030 rounds, and 5,325 tactical silver labels; v0.1 remains as the original single-match baseline. Opening duels and post-plant phases come directly from event facts; trade kills, Utility Bursts, and Retake Contacts use explicit temporal rules. A weakly supervised Execute Candidate is added only when a T-side utility sequence is followed by a plant. Every label retains its rule version, confidence, review status, and evidence event IDs. The result is explicitly a reproducible silver-label dataset, not expert-annotated gold data.

---

## 📝 License

MIT © 2026

---

<div align="center">
<sub>Built with ❤️ for the CS2 competitive scene.</sub>
</div>

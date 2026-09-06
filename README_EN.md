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

The evaluation tools now include 160 unscored same-corpus retrieval runs and a complete unseen-series pipeline pilot (2 maps, 44 rounds, all checks passed). The offline suite has 96 passing tests. Independent relevance labels and broader research validation remain pending. See [retrieval experiment](docs/FAIR_RETRIEVAL_RUN.md) and [unseen-series pilot](docs/UNSEEN_MATCH_PILOT.md).

The latest local milestone adds roster-based player denominators and an offline test environment: complete rosters for 1,023 valid rounds across 49 maps, 87 passing offline tests, and a clean frontend build. Remote CI has not run. See [implementation status](docs/IMPLEMENTATION_PROGRESS.md), [player data contract](docs/PLAYER_PROFILE_DATA_CONTRACT.md), and [offline reproduction](docs/OFFLINE_VALIDATION.md).

---

## 📖 Overview

**CS2 Coach Agent** is an intelligent CS2 professional match analysis system built on a **multi-agent state machine** core with **advanced RAG tactical retrieval** capabilities.

It can:
- Ingest `.dem` demo files directly, leveraging `demoparser2` to automatically parse kill chains, grenade landing positions, flash-blind sequences, and bomb plant events for every round.
- Built-in **HLTV data scraper and demo downloader**, supporting automated acquisition of high-value professional match Demo datasets.
- Drive **Supervisor (bounded tool calling) → Tools → Router → parallel task retrieval → Critique → Analyst → Coach → Verifier** with a feedback-based **Refine Loop**; knowledge ingestion requires verification, explicit approval, and a configuration switch.
- The Critique node triggers a **feedback-based retry loop** when retrieval quality falls below a threshold; after the maximum attempts it preserves the low-quality signal instead of pretending the context passed.
- Compute and report verifiable kills, openings, side splits, and post-plant conversions in code; `qwen3.8-flash` can only choose training priorities from an allowlist and cannot author report facts.
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
| **LLM** | Alibaba Cloud DashScope / Qwen | `qwen3.8-flash` model inference (via OpenAI-compatible API) |
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
Coach: model-selected allowlisted priorities, code-rendered evidence advice
        ▼
Verifier: current [C#], historical [E#], and unsupported-claim checks
```

The parser stores observable events and never infers that utility caused a round win. Analyst and Coach output is rendered from deterministic facts; the model only orders allowlisted training topics. This separates raw facts, model selection, and coaching recommendations.

### 2. LangGraph State Machine and Bounded Agents

All nodes communicate through `GraphState`. Important fields include:

| Field | Purpose |
|-------|---------|
| `metrics` | Code-computed team scores, valid kills, opening conversions, utility, and plant metrics |
| `current_evidence` | Deterministic evidence from the uploaded Demo, cited as `[C#]` |
| `analysis_plan` | Router tasks for opening, utility, round flow, and map context |
| `retrieval_task_results` | Per-task coverage, source counts, and warnings |
| `retrieval_evidence` | Historical Milvus/GraphRAG comparison evidence cited as `[E#]` |
| `agent_trace` / `tool_trace` | Execution trace shown by the frontend |
| `verification_report` | Unknown citations, missing citations, and review status |

The Supervisor may choose an analysis mode through an allowlisted tool, but cannot create graph nodes, execute code, access the network, or write to the knowledge base. Unsupported or failed tool calls use a deterministic fallback, so model output cannot change the workflow topology.

### 3. Milvus Hybrid RAG

The vector collection is `cs2_tactical_knowledge`. Each document keeps `map`, `match_id`, `round_number`, `tactic_type`, `parent_id`, and `parent_content` metadata.

Each retrieval follows this sequence:

1. Use Router-generated CS2 terminology by default; add LLM query rewriting only when `LLM_AUXILIARY_CALLS_ENABLED=true`.
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
- The dashboard separates current-Demo `[C#]` evidence from historical `[E#]` comparisons and marks completed tasks that still need quality review.
- The GraphRAG panel loads maps, nodes/edges, Global Search, player profiles, and team comparisons through read-only endpoints.
- The subgraph is drawn with SVG instead of a large visualization dependency; CSS breakpoints collapse the layout on mobile.

### 6. Reliability and Review Boundaries

- Deterministic metrics run before any LLM call; environment deaths, suicides, and team kills are excluded while team scores, opening conversion, utility, and plants are computed in code.
- Critique evaluates evidence relevance and coverage, not whether the model agrees with a tactic.
- Verifier is LLM-free and checks unknown `[C#]/[E#]` citations, unsupported recommendations, and current-match claims backed only by historical evidence.
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
MODEL_NAME=qwen3.8-flash
LLM_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=1400
LLM_ENABLE_THINKING=false
LLM_AUXILIARY_CALLS_ENABLED=false

# Milvus Vector Database
MILVUS_URI="http://localhost:19530"
MILVUS_TOKEN=""

# Celery Message Queue (requires local Redis)
CELERY_BROKER_URL="redis://localhost:6379/0"
CELERY_RESULT_BACKEND="redis://localhost:6379/1"
```

Alternatively, enter the key in the “Submit Match Demo” panel after starting the frontend. The UI calls `PUT /api/settings/llm/key`; the key is written only to the local `data/runtime/dashscope_api_key` file with `0600` permissions and is never stored in the browser, Git, API response, or Celery payload. Both API and worker processes read it on the next model call without a restart. Writes are loopback-only, and `GET /api/settings/llm` returns configuration status without exposing the key.

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

The same SQLite graph now powers cross-match analytics. Player profiles aggregate kills, deaths, assists, opening duels, trades, utility, plants, and participation in all six tactical sequence types. Both player profiles and two-player comparisons can be restricted to the same map, T/CT side, and opponent. Team comparison normalizes every sequence to 100 observed team rounds so unequal match counts do not distort totals. Tactical slices use the same filters, then calculate round conversion after opening wins/losses, trade rounds, post-plants, retake contacts, and execute candidates. They also expose player responsibility shares for openings, trades, and utility bursts. Natural-language team and player queries return deterministic Chinese briefs with `graph:{match}:{map}:{round}` sources; opening a source shows its timeline and opposite-outcome comparisons. These are descriptive metrics, not causal claims. A `round_end` without a winner is treated as a technical-pause or round-restore marker and excluded from official rounds. When a GOTV demo omits native `player_blind` events, the parser compares `flash_duration` immediately before and at each `flashbang_detonate` tick to recover victim, thrower, team, area, and duration fields, marking them with `source=flash_duration_delta`. A single detonation in a tick has an exact thrower; simultaneous detonations retain every `attacker_candidates` entry with `attribution=simultaneous_flash_candidates` instead of inventing a unique attribution.

Global Search now extracts team, map, T/CT side, and opponent from natural-language questions and returns the matching tactical slice as its highest-priority structured evidence. When two teams and comparison intent are present, it generates a same-context tactical comparison. Examples include `Falcons Dust2 T-side opening conversion`, `Falcons versus Spirit retake performance`, and `compare Spirit and Vitality trade rounds on Nuke CT`. This path is deterministic and adds no LLM call.

### 4. Start the API and Worker

```bash
make dev
```

`qwen3.8-flash` enables deep thinking by default; this project disables it and uses one model call per match for Coach by default. Supervisor, routing, Critique, and Analyst stay deterministic and local, generation is capped at 1,400 tokens, and the UI displays token usage for the run. Set `LLM_AUXILIARY_CALLS_ENABLED=true` only when extra query-rewrite and LLM-Critique calls are worth the quota. Quota rejection is not retried; Coach falls back to local priority rules. Local development uses Celery's `solo` pool by default to avoid macOS `fork` conflicts with native FastEmbed/ONNX runtimes. Linux deployments can opt into prefork with `CELERY_POOL=prefork CELERY_CONCURRENCY=4 make worker`. Temporary uploaded Demos are deleted after task completion.

### 5. Start the Frontend Review Console

In a second terminal:

```bash
make frontend-install
make frontend
```

Open `http://localhost:5173`. The console provides Demo upload, async progress, metric cards, Analyst/Coach reports, evidence citations, a GraphRAG subgraph, Global Search, cross-match player profiles, five-team tactical comparison, and contextual tactical slices. Team queries show a deterministic Chinese coaching brief before the raw graph evidence. `[G#]` citations prioritize rounds for the requested metric; key-round samples can also be filtered by opening, trade, utility, execute, post-plant, retake, and outcome. Opening a sample shows its raw timeline and recommends opposite-outcome rounds with the same map and side, ranked by tactical-label and site overlap. Vite proxies `/api` requests to port `8001`.

Read-only GraphRAG display endpoints:

```text
GET /api/graph/stats
GET /api/graph/maps
GET /api/graph/search?q=... # answer brief plus raw evidence results
GET /api/graph/round?source_id=graph:2396609:Dust2:1&team=Falcons # optional team adds opposite-outcome analogues
GET /api/graph/subgraph?map_name=Mirage
GET /api/graph/players?team=Falcons
GET /api/graph/players/{steamid_or_nickname}?map_name=Dust2&side=T&opponent=Spirit
GET /api/graph/players/compare?players={id1},{id2}&map_name=Dust2&side=T
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
│       ├── workflow.py            # LangGraph state machine builder (with Refine Loop)
│       └── nodes/                 # Controlled agent and deterministic tool nodes
│           ├── supervisor_node.py # Supervisor: bounded analysis modes
│           ├── tool_node.py       # Tools: deterministic metrics first
│           ├── router_node.py     # Router: metadata extraction & filter signal
│           ├── retrieve_node.py   # Retrieve: vector search dispatch
│           ├── critique_node.py   # Critique: retrieval quality review (0.0-1.0)
│           ├── analyst_node.py    # Analyst: deterministic fact report
│           ├── coach_node.py      # Coach: allowlisted priority + evidence advice
│           └── verify_node.py     # Verifier: citation and fact checks
├── scripts/                       # Utility Scripts
│   ├── seed_knowledge.py          # Milvus knowledge base seed script
│   ├── build_graph.py             # Build GraphRAG graph and communities
│   ├── evaluate_retrieval.py      # Offline RAG smoke evaluation
│   ├── evaluate_tactical_queries.py # Tactical natural-language contract evaluation
│   ├── fetch_recent_demos.py      # HLTV professional Demo fetch entrypoint
│   ├── analyze_local.py           # Local demo direct analysis entry
│   └── test_webhook.py            # Webhook API test script
├── datasets/evaluation/           # Fixed query set and reproducible report
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
> Supervisor is deterministic by default. When auxiliary model calls are enabled, it can only choose existing modes and retrieval tasks through the allowlisted `select_analysis_plan` tool. Tools computes deterministic metrics first.

### 📚 Retrieve (Tactical Knowledge Retriever)
> Invokes `KnowledgeBaseClient` with Router queries and Milvus native dense + BM25 hybrid retrieval. LLM query rewriting is an optional quota expense.

The knowledge base defaults to Milvus native dense + BM25 hybrid retrieval and preserves match/map parent summaries with each evidence hit. Set `RAG_HYBRID_ENABLED=false` for the legacy dense fallback. Run `make eval-rag` for the fixed-query retrieval smoke evaluation.

### ⚖️ Critique (Retrieval Quality Judge)
> Code scores task coverage, map match, team match, and evidence count. **When the score falls below 0.7, that feedback is added to the next query, with up to three attempts.**

### ✅ Verifier (Fact and Citation Checker)
> Uses no LLM. It checks that `[E#]` citations exist, rejects unknown evidence IDs, and flags key recommendations without evidence markers.

### 🔬 Analyst (Deterministic Fact Report)
> Uses no LLM. It reports score, side splits, opening conversion, post-plant conversion, defuses, and utility counts; unavailable metrics are explicit and no subjective cause is added.

### 🎯 Coach (Bounded Training Decision)
> `qwen3.8-flash` only calls `select_coaching_priorities` to choose 2–3 topics from opening follow-up, post-plant, utility review, and side transition. Code renders the final report and `[C#]` citations, so the model cannot add roles, positions, utility effects, or tactical causality.

### 🔐 Knowledge Ingestion Review Gate
> Self-learning ingestion is disabled by default. It runs only when `AUTO_INGEST_ENABLED=true`, `extra_data.knowledge_approved=true`, the source is marked high quality, and Verifier passes. Otherwise the result is returned as `knowledge_review.status=pending_review`; an operator can review it and submit it through `/api/knowledge/ingest`.

### ✅ Local Validation

```bash
make test       # Unit and integration tests
make eval-rag   # Fixed-query Milvus RAG evaluation
make eval-tactics # 30-case GraphRAG tactical query contract evaluation
make eval-players # 20 contextual player-query contract cases
make eval-v1      # 50 contract cases + 50 retrieval queries across five modes
make eval-negatives # 12 independent synthetic development negatives
make eval-holdout # frozen 30-query regression validation; original baseline retained
make graph-build
make silver-dataset # build evidence-linked tactical silver annotations
```

Community summaries are currently deterministic and extractive: they summarize parsed facts, preserve round-level sources, and do not promote small-sample observations into universal professional tactics.

`make silver-dataset` writes round-level research data to `datasets/silver/v0.2/`. v0.2 uses the fixed 20-match selection in `datasets/selections/five_teams_recent_20_v1.json`, covering 49 maps, 1,030 rounds, and 5,325 tactical silver labels; v0.1 remains as the original single-match baseline. Opening duels and post-plant phases come directly from event facts; trade kills, Utility Bursts, and Retake Contacts use explicit temporal rules. A weakly supervised Execute Candidate is added only when a T-side utility sequence is followed by a plant. Every label retains its rule version, confidence, review status, and evidence event IDs. The result is explicitly a reproducible silver-label dataset, not expert-annotated gold data.

### Unified GraphRAG Evaluation

`datasets/evaluation/tactical_queries_v1.json` and `player_queries_v1.json` contain 50 structured contract cases. `retrieval_queries_v2.json` adds 50 deterministic retrieval queries covering seven maps, four intents, five target teams, five representative players, bilingual paraphrases, and no-answer negatives. `make eval-v1` evaluates 50 contract cases plus 152 retrieval checks without remote query rewriting. Current scores are graph-only and hybrid 100.00, vector-only 77.72, community-only 73.76, and no-RAG 4.46. Vector retrieval itself passes 50/50 queries; its lower combined score reflects the absence of the graph's structured team/player contracts. Reports are written to `datasets/evaluation/cs2_coach_v1_report.json` and `retrieval_v2_report.json`. This remains a silver-standard engineering evaluation, not expert gold evaluation of coaching quality or player skill, and it does not establish causality.

The first frozen run of `retrieval_queries_holdout_v1.json` uses 30 different phrasings, players, match filters, and harder negatives. Graph-only and hybrid score 97.99: all 27 positive queries pass, while all three open-ended unknown-entity/cross-domain negatives are falsely retrieved. Vector-only passes 24/30 queries and 93/99 retrieval checks, for a 65.77 combined score. The original baseline remains in `datasets/evaluation/cs2_coach_holdout_v1_report.json`. Frozen queries must not be rewritten; subsequent fixes use independent development examples and retain evaluation history.

---

### Query-boundary repair validation (2026-09-06)

All 12 independent synthetic negatives pass. The original development set remains 50/50 for Vector, Graph and Hybrid, with 50/50 structured contracts. Final held-out Graph and Hybrid results are **30/30 queries, 99/99 checks and a 100.00 combined score**: all 27 positive queries are retained and all three negatives abstain. Vector reaches **27/30, 96/99 and 67.79**, with no loss of previously passing queries; three intent checks remain unsuccessful.

There were **two** held-out runs during this repair. The first exposed over-rejection of ordinary descriptions and explicit map context; independent positive regressions were added before the final run. The failed attempt is retained in `datasets/evaluation/cs2_coach_holdout_v1_attempt1_report.json`; the final result is `datasets/evaluation/cs2_coach_holdout_v1_fixed_report.json`. The original baseline and frozen queries are unchanged. This is regression validation, not a fresh blind test or evidence of unseen-match generalization.

Validation: 80 tests passed with three dependency warnings, and the frontend production build passed. Retrieval benchmarks made no remote model calls. See the [repair validation record](docs/NEGATIVE_RETRIEVAL_FIX.md).

Entity constraints cover English profile, subject/map, opponent and comparison syntax while retaining Chinese aliases. Graph search checks indexed identities; vector evidence uses complete name boundaries. Without explicit context, generic terms such as `match` and `professional` no longer establish the domain. Caller-provided map/match filters remain valid context. This is a bounded query grammar, not general-purpose named entity recognition.

See the [engineering and research roadmap](docs/PROJECT_IMPROVEMENT_ROADMAP.md) for independent-match evaluation, fair ablations, human review and key-free CI. Engineering pass rates are not measures of coaching quality or unseen-match generalization.


## 📝 License

MIT © 2026

---

<div align="center">
<sub>Built with ❤️ for the CS2 competitive scene.</sub>
</div>

PYTHON_BOOTSTRAP ?= python3.11
PYTHON ?= .venv/bin/python
COMPOSE ?= docker compose
API_PORT ?= 8001

INFRA_SERVICES = redis etcd minio standalone
CELERY = $(PYTHON) -m celery -A app.core.celery_app worker --loglevel=info
UVICORN = $(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(API_PORT)

.PHONY: bootstrap infra status seed graph-build silver-dataset eval-rag eval-tactics frontend-install frontend frontend-build api worker dev analyze fetch-demos test clean

bootstrap:
	@command -v $(PYTHON_BOOTSTRAP) >/dev/null || (echo "Missing $(PYTHON_BOOTSTRAP); override PYTHON_BOOTSTRAP=/path/to/python3.11" && exit 1)
	@test -x $(PYTHON) || $(PYTHON_BOOTSTRAP) -m venv .venv
	@$(PYTHON) -m pip install --upgrade pip
	@$(PYTHON) -m pip install -r requirements-dev.txt
	@test -f .env || (cp .env.example .env && echo "Created .env; fill in DASHSCOPE_API_KEY before using LLM features.")
	@$(MAKE) infra

infra:
	@$(COMPOSE) up -d $(INFRA_SERVICES)

status:
	@$(COMPOSE) ps

seed:
	@$(PYTHON) scripts/seed_knowledge.py

graph-build:
	@PYTHONPATH=. $(PYTHON) scripts/build_graph.py

silver-dataset:
	@PYTHONPATH=. $(PYTHON) scripts/build_silver_dataset.py $(ARGS)

frontend-install:
	@npm --prefix frontend install

frontend:
	@npm --prefix frontend run dev

frontend-build:
	@npm --prefix frontend run build

eval-rag:
	@$(PYTHON) scripts/evaluate_retrieval.py

eval-tactics:
	@$(PYTHON) scripts/evaluate_tactical_queries.py $(ARGS)

api:
	@$(UVICORN)

worker:
	@$(CELERY)

dev: infra
	@trap 'kill $$API_PID $$WORKER_PID 2>/dev/null || true' INT TERM EXIT; \
		$(UVICORN) & API_PID=$$!; \
		$(CELERY) & WORKER_PID=$$!; \
		wait $$API_PID $$WORKER_PID

analyze:
	@test -n "$(DEMO)" || (echo "Usage: make analyze DEMO=data/your_match.dem" && exit 1)
	@$(PYTHON) scripts/analyze_local.py "$(DEMO)"

fetch-demos:
	@PYTHONPATH=. $(PYTHON) scripts/fetch_recent_demos.py $(ARGS)

test:
	@$(PYTHON) -m pytest -q

clean:
	@$(COMPOSE) down

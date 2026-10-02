# Cohortex developer commands. Run `make help` for the list.
# Works on Linux, macOS and Windows via WSL2.

SHELL := /bin/bash
COMPOSE := docker compose -f deploy/compose/docker-compose.yml --env-file .env
PY_SRC := services/agent-service mcp pipelines evals/harness

.DEFAULT_GOAL := help

.PHONY: help
help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.env:
	cp .env.example .env
	@echo "Created .env from .env.example; edit it before running services."

# ---------------------------------------------------------------- infrastructure
.PHONY: up
up: .env ## Start local infrastructure (Postgres+pgvector, Kafka, OTel Collector, Jaeger)
	$(COMPOSE) up -d --wait postgres kafka
	$(COMPOSE) up -d otel-collector jaeger
	@echo "Jaeger UI: http://localhost:16686"

.PHONY: down
down: .env ## Stop local infrastructure (keeps data volumes)
	$(COMPOSE) down

.PHONY: reset
reset: .env ## Stop infrastructure and DELETE local data volumes
	$(COMPOSE) down -v

.PHONY: ps
ps: .env ## Show infrastructure status
	$(COMPOSE) ps

.PHONY: logs
logs: .env ## Follow infrastructure logs
	$(COMPOSE) logs -f

.PHONY: seed
seed: ## Load fixture data (available after WP-03)
	@echo "make seed is implemented in WP-03 (batch ingest). Nothing to load yet." && exit 1

# ---------------------------------------------------------------- python
.PHONY: sync
sync: ## Install the Python workspace (all packages + dev tools)
	uv sync --all-packages

.PHONY: lint
lint: ## Lint and format-check Python (Java lint arrives with the first Java module)
	uv run ruff check .
	uv run ruff format --check .

.PHONY: fmt
fmt: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

.PHONY: typecheck
typecheck: ## Strict mypy over all Python packages and their tests
	uv run mypy $(PY_SRC)

.PHONY: test-python
test-python: ## Run Python tests
	uv run pytest

# ---------------------------------------------------------------- java
.PHONY: test-java
test-java: ## Build and test Java modules (needs a JDK 17+ to launch Gradle)
	./gradlew build

# ---------------------------------------------------------------- all
.PHONY: test
test: test-python test-java ## Run all tests

.PHONY: check
check: lint typecheck test ## Everything CI runs, locally

.PHONY: eval
eval: ## Run the eval gate (available after WP-07)
	@echo "make eval is implemented in WP-07 (eval harness)." && exit 1

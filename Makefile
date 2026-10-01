API := apps/api
WEB := apps/web
PROFILE ?= low

LOCAL_DB := postgresql://ahq:ahq@localhost:5432/ahq
LOCAL := DATABASE_URL=$(LOCAL_DB) DATABASE_URL_UNPOOLED=$(LOCAL_DB) \
	QDRANT_URL=http://localhost:6333 QDRANT_API_KEY= \
	AHQ_ENV=local AHQ_OPERATOR_TOKEN=local-operator-token \
	AHQ_QUEUE_BACKEND=inprocess AHQ_TOOL_TRANSPORT=asgi AHQ_SEGMENT_BUDGET_S=60 AHQ_EVAL_BACKEND=inprocess

.PHONY: help setup up up-pooled down migrate seed embed kb sim sim-check eval-retrieval eval-prompts eval-gate eval-safety eval-fallback api api-offline web check check-api check-web fix test test-db test-live e2e-web openapi charts

help: ## List the available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install Python and web dependencies
	cd $(API) && uv sync
	cd $(WEB) && pnpm install

up: ## Start local Postgres and Qdrant
	docker compose up -d --wait postgres qdrant

up-pooled: ## Start Postgres, Qdrant and PgBouncer (transaction mode)
	docker compose --profile pooled up -d --wait

down: ## Stop local services
	docker compose --profile pooled down

migrate: ## Migrate the local database
	cd $(API) && $(LOCAL) uv run ahq db migrate

seed: ## Load the τ³ store and generated data into the local database
	cd $(API) && $(LOCAL) uv run ahq db seed

embed: ## Embed reviews and ticket messages (PROFILE=mock for hashed vectors)
	cd $(API) && $(LOCAL) AHQ_MODEL_PROFILE=$(PROFILE) uv run ahq db embed

sim: ## Play a simulated day against the local database (SCENARIO=normal-day SEED=7)
	cd $(API) && $(LOCAL) uv run ahq sim run --scenario $(or $(SCENARIO),normal-day) --seed $(or $(SEED),7)

sim-check: ## Play a scenario with agents and grade the result (SCENARIO=carrier-delay TRIALS=1)
	cd $(API) && $(LOCAL) AHQ_TOOL_TRANSPORT=direct uv run ahq sim check --scenario $(or $(SCENARIO),carrier-delay) \
		--trials $(or $(TRIALS),1) --profile $(PROFILE)

kb: ## Rebuild the knowledge base in the local Qdrant (PROFILE=mock for hashed vectors)
	cd $(API) && $(LOCAL) AHQ_MODEL_PROFILE=$(PROFILE) uv run ahq kb ingest && $(LOCAL) uv run ahq kb stats

eval-retrieval: ## Compare search modes on labeled questions
	cd $(API) && $(LOCAL) AHQ_MODEL_PROFILE=$(PROFILE) uv run ahq eval retrieval --chart

eval-prompts: ## Single-turn prompt checks with promptfoo
	cd evals/promptfoo && PROMPTFOO_PYTHON=$(CURDIR)/$(API)/.venv/bin/python PROMPTFOO_DISABLE_TELEMETRY=1 \
		npx --yes promptfoo@0.123.1 eval -c promptfooconfig.yaml --env-file $(CURDIR)/.env --no-cache

eval-gate: ## Run the eval gate on a candidate version (CANDIDATE=support@2)
	cd $(API) && $(LOCAL) AHQ_TOOL_TRANSPORT=direct AHQ_MODEL_PROFILE=$(PROFILE) uv run ahq eval gate --candidate $(CANDIDATE)

eval-safety: ## Run the safety suite in memory (INPUT_CHECK=off to disable the input check)
	cd $(API) && DATABASE_URL= DATABASE_URL_UNPOOLED= QDRANT_URL= QDRANT_API_KEY= LANGSMITH_API_KEY= \
		uv run ahq eval safety --profile $(PROFILE) $(if $(filter off,$(INPUT_CHECK)),--no-input-check,)

eval-fallback: ## Run an agent's gate suite on its model and its fallback (AGENT=support)
	cd $(API) && $(LOCAL) AHQ_TOOL_TRANSPORT=direct uv run ahq eval fallback --agent $(or $(AGENT),support) --profile $(PROFILE)

api: ## Run the api on :8000 against local services (PROFILE=mock|low|medium|high)
	cd $(API) && $(LOCAL) AHQ_MODEL_PROFILE=$(PROFILE) uv run uvicorn ahq.main:app --reload --port 8000

api-offline: ## Run the api on :8000 with no services or keys: memory storage and rule-based agents
	cd $(API) && DATABASE_URL= DATABASE_URL_UNPOOLED= QDRANT_URL= AHQ_ENV=local AHQ_MODEL_PROFILE=mock \
		AHQ_SEED_MEMORY=1 AHQ_QUEUE_BACKEND=inprocess AHQ_TOOL_TRANSPORT=direct AHQ_OPERATOR_TOKEN=local-operator-token \
		AHQ_EVAL_BACKEND=inprocess AHQ_FAKE_PACE=$(or $(PACE),1.2) AHQ_QUEUE_CONCURRENCY=8 \
		uv run uvicorn ahq.main:app --port 8000

web: ## Run the control room on :3000
	cd $(WEB) && AHQ_OPERATOR_TOKEN=local-operator-token pnpm dev

check: check-api check-web ## Lint, format check, type check and import contracts

check-api:
	cd $(API) && uv run ruff check && uv run ruff format --check
	cd $(API) && uv run basedpyright && uv run lint-imports

check-web:
	cd $(WEB) && pnpm lint && pnpm typecheck

fix: ## Apply formatting and safe lint fixes
	cd $(API) && uv run ruff format && uv run ruff check --fix
	cd $(WEB) && pnpm format

test: ## Run every offline test (database tests need `make up-pooled`)
	cd $(API) && uv run pytest
	cd $(WEB) && pnpm test

test-db: up-pooled ## Run the tests that need Postgres and PgBouncer
	cd $(API) && AHQ_REQUIRE_SERVICES=1 uv run pytest -m "db or pooled"

test-live: ## Run the live checks against real services
	cd $(API) && uv run pytest -m live -v

e2e-web: ## Playwright tests against the offline api
	cd $(WEB) && pnpm e2e

charts: ## Draw the README charts from reports in evals/results
	cd $(API) && uv run ahq charts \
		$(foreach report,$(sort $(wildcard evals/results/tau3-medium-test-*.json)),--tau3 $(CURDIR)/$(report)) \
		--safety-on $(CURDIR)/$(lastword $(sort $(wildcard evals/results/safety-low-screen-*.json))) \
		--safety-off $(CURDIR)/$(lastword $(sort $(wildcard evals/results/safety-low-noscreen-*.json)))

openapi: ## Regenerate the web app's api types
	cd $(API) && uv run ahq openapi --output ../web/lib/api/openapi.json
	cd $(WEB) && pnpm openapi

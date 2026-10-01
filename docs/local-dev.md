# Local development

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13)
- Node 22 and pnpm 10
- Docker, for Postgres and Qdrant (not needed offline)

## Offline

No services and no keys. The api runs on memory storage with rule-based agents and publishes the recorded day in
`data/recordings/offline-day.json.gz` at startup.

```bash
make setup
make api-offline            # :8000; PACE=0 makes the rule-based agents answer at once
make web                    # :3000
```

<http://localhost:3000> shows the recorded day as a visitor sees it. "Sign in as local admin" in the sidebar opens the
live control room and the admin pages: play a simulated day, decide approvals, record and publish a day.

## With services

```bash
cp .env.example .env
make setup
make up-pooled              # Postgres 18 with pgvector, Qdrant, PgBouncer
make migrate
make seed                   # the τ³ store and generated data
make kb PROFILE=mock        # knowledge base with hashed vectors; other profiles embed with voyage-4
make api PROFILE=mock       # or low, medium, high with OPENROUTER_API_KEY set
make web
```

Talk to Support as a customer:

```bash
TOKEN="Authorization: Bearer local-operator-token"
curl -X POST localhost:3000/api/tickets -H "$TOKEN" -H 'content-type: application/json' \
  -d '{"message": "Hi, I am Yusuf Rossi, zip 19122. Where does a refund for a return go?"}'
curl localhost:3000/api/tickets/<ticket_id>
curl -X POST localhost:3000/api/work/<work_item_id>/messages -H "$TOKEN" -H 'content-type: application/json' \
  -d '{"text": "Thanks, that is all."}'
```

Play a carrier-delay day with its alerts going to the agents:

```bash
curl -X POST localhost:3000/api/sim/start -H "$TOKEN" -H 'content-type: application/json' \
  -d '{"scenario": "carrier-delay", "alerts_to_agents": true}'
curl localhost:3000/api/incidents
```

`uv run ahq --help` in `apps/api` lists the command-line tools: migrations, seeding, the knowledge base, the
simulator, evals, MCP tokens.

## Checks and tests

```bash
make check                  # ruff, basedpyright, import-linter, ESLint, tsc
make test                   # api and web unit tests, offline
make test-db                # tests that need Postgres and PgBouncer
make e2e-web                # Playwright against the offline api
make test-live              # real providers; costs a few cents
```

Tests block the network except localhost. Models, embeddings and rerankers are replaced by scripted fakes.

## Deployment

`vercel.json` defines one Vercel project with two services: `web` (Next.js) and `api` (FastAPI, from
`apps/api/pyproject.toml`). `/api/*` and `/mcp/*` route to the api, everything else to the web app. The api's build
runs `ahq db migrate`. Queue subscribers are declared in `pyproject.toml` under `[[tool.vercel.subscribers]]`. A daily
cron keeps the Qdrant cluster active.

Environment variables are listed in `.env.example`. A deployment needs at least the database and Qdrant URLs,
`OPENROUTER_API_KEY`, `AHQ_OPERATOR_TOKEN`, `AHQ_MCP_TOKEN_SECRET`, `CRON_SECRET`, `AHQ_QUEUE_BACKEND=vercel` and
`AHQ_TOOL_TRANSPORT=http`. Admin sign-in also needs `AUTH_SECRET`, a GitHub OAuth app (`AUTH_GITHUB_ID`,
`AUTH_GITHUB_SECRET`) and `AHQ_ADMIN_GITHUB_ID`. Without `AUTH_SECRET` the control room is read-only.

After a deploy, seed the database once (`ahq db seed`, `ahq db embed`, `ahq kb ingest` against the deployment's
database and Qdrant). The eval gate needs `AHQ_GITHUB_TOKEN` and `AHQ_GITHUB_REPO` on the api, and the repository
secrets `AHQ_OPERATOR_TOKEN`, `OPENROUTER_API_KEY` and `LANGSMITH_API_KEY` with the variable `AHQ_API_URL`.

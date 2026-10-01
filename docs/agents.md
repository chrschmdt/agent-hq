# Agents

![One turn of a ticket](img/support-loop.svg)

## The team

| | Dispatcher | Support | Ops | Insights |
|---|---|---|---|---|
| Works on | every new work item | tickets | alerts, flags | handoffs from Ops, flags |
| Tools | none | orders, knowledge search, `flag_pattern` | analytics, knowledge search | analytics, knowledge search, drafts |
| Autonomy | observe | act within limits, one customer | observe, whole store | draft, whole store |
| Answer | `RouteDecision` | `SupportTurn` | `IncidentReport` | `ProposalSet` |
| Limits per turn | 1 call, $0.02 | 25 calls, $0.50 | 15 calls, $0.50 | 15 calls, $0.50 |

A QA reviewer grades finished runs, and a guard model screens customer text. Each agent names a model role, and the
active profile maps roles to models:

| Profile | Dispatcher | Support, Ops, Insights | QA | Simulated customers |
|---|---|---|---|---|
| `mock` | rules | rules | rules | rules |
| `low` | `gpt-6-luna` | `gpt-6-luna` | `gpt-6-luna` | `gpt-6-luna` |
| `medium` | Haiku 4.5 | Sonnet 5.5 | `gpt-6-sol` | `gpt-6-luna` |
| `high` | Sonnet 5.5 | Opus 5.5 | `gpt-6-sol` | `gpt-6-sol` |

Everything in a prompt before its `## Context` heading is the same for every piece of work, so providers can cache
it. Support's prompt includes τ³'s retail policy verbatim.

Every turn ends with a typed answer. On Anthropic models the reply schema is sent as structured output next to the
tools, or as a `reply` tool for models that do better that way. On the OpenAI route the schema is in the prompt and an
unreadable reply is repaired with one typed call. Claude models with adaptive thinking return a summary of their
reasoning, which the run inspector shows.

## Handoffs and flags

![A handoff within one work item, and a flag that starts another](img/handoff-vs-flag.svg)

- A **handoff** moves work to the next agent in the same thread. The loop ends with
  `Command(graph=Command.PARENT, goto=...)` carrying its whole state, and the next agent gets a brief in its own
  channel.
- A **flag** (`flag_pattern`) creates a new work item with its own thread. Alerts and flags carry a key, so the same
  signal becomes work once.

## Tools and permissions

One catalog defines every tool: its arguments, effect (read, write, draft), whether it is scoped to the verified
customer, and whether it needs approval. The same catalog builds the MCP servers and the direct provider used in
tests and evals.

| Server | Tools |
|---|---|
| `orders` | τ³'s retail tools (lookups, cancellations, modifications, returns, exchanges), `issue_refund`, `transfer_to_human_agents` |
| `knowledge` | `knowledge_search`, `knowledge_get_article`, `knowledge_draft_article` |
| `analytics` | `analytics_get_kpis`, `analytics_run_sql`, `analytics_similar_tickets`, `analytics_cluster_tickets`, `analytics_recent_changes` |

![A gated call across two segments](img/gated-call.svg)

- **Checked twice.** The graph's `authorize` node decides every call (allow, deny, needs approval), and the MCP server
  decides it again before running it.
- **Signed context.** Each call carries a hidden, signed context: thread, tool call, verified customer, approval id,
  expiry. The model never sees it, and a forged or expired one is denied.
- **Customer scope.** The first successful customer lookup pins the verified customer. Support cannot read or change
  another customer's orders.
- **Approvals.** Returns, exchanges and item changes that pay back more than $100, and every goodwill refund, wait
  for a person. The graph interrupts once per gated call, and the person approves, edits or rejects.
- **Once only.** A write records its audit row in the same transaction as the store change.

## Retrieval

Hybrid search over the knowledge base: one Qdrant query with dense (`voyage-4`) and BM25 prefetches fused by RRF,
then `rerank-2.5`. The mode was chosen by the retrieval eval ([Evals](evals.md#retrieval)). Passages carry
versioned ids, and every Support reply's citations are checked: a passage that was never retrieved, or not in effect
on the simulated day, sends the reply back once for a fix.

## Analytics

Ops and Insights query the store with SQL, behind three layers:

1. A parser (sqlglot) allows one `SELECT` over the `retail`, `support` and `kpi` schemas, rejects writes anywhere in
   the tree and risky functions, and forces a `LIMIT`.
2. The query runs as a `NOLOGIN` role with `SELECT` grants only.
3. The transaction is read-only with a statement timeout.

## Guardrails

![The layers an attack meets](img/guardrails.svg)

- **Input check.** Customer text is screened before any agent reads it: free patterns first, then one call to the
  guard model. Flagged text goes to a person and the customer gets a holding reply.
- **Reply check.** Support's reply is held back if it contains another customer's identifiers or any link.
- **Traces.** Customer details are redacted before traces reach LangSmith.

## Managing the team

![How a change goes live](img/management.svg)

- **Versions.** Every agent version lives in a registry: draft, evaluated, canary, live, retired. A version may change
  the prompt, model and limits, and only narrow the tools. An agent keeps the same version for the whole work item.
- **Eval gate.** A candidate runs the agent's suite against the live version on the same cases, in GitHub Actions. It
  passes when it scores at most 0.10 below live and costs at most 1.5 times as much per case.
- **Canary.** A passed version takes 20% of new work. After at least 6 runs it is rolled back when the Wilson lower
  bound (95%) of its escalation, error or rejection rate exceeds live's by a set margin, when it costs more than 1.5
  times as much, or when its calibrated QA scores drop. It is promoted after 30 clean runs.
- **QA reviewer.** Grades a sample of runs, plus every escalation, rejected approval and canary run, against each
  agent's rubric. A criterion counts only once blind human labels show it is calibrated (TPR at least 0.80, TNR at
  least 0.70).
- **Limits.** Daily budgets per agent and in total, a breaker per model that switches to its fallback, a breaker per
  agent, and a kill switch. All state is in Postgres, so every instance sees the same limits.

![A model call under load](img/calls.svg)

Calls to each provider are capped by slots leased in Postgres. A busy answer (429 or 5xx) is retried with full
jitter, never sooner than `retry-after`. A call that cannot get a slot in time defers its work instead of failing it.

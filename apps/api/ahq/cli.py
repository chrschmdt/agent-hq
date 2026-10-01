from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import secrets
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import httpx
import typer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.adapters.clock import WallClock
from ahq.adapters.embedding_cache import CachingEmbedder
from ahq.app.container import (
    make_chat_models,
    make_sparse,
    make_vector_store,
    open_container,
    open_embedder,
    open_reranker,
)
from ahq.config import CONFIG_DIR, ProfileName, load_model_catalog, load_retrieval_config, load_world_config
from ahq.db.activity import PgActivityStore, activity_counts
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.migrate import upgrade
from ahq.db.repos import PgBaseline, PgEventLog, PgRetailRepo, PgSimStore, PgTeamRecords, PgWorldRepo
from ahq.domain import GateParams, Suite
from ahq.evals.charts import merge_trials, pass_k_svg, safety_svg
from ahq.evals.dispatcher import build_cases, load_cases, run_dispatcher_eval, write_cases
from ahq.evals.fallback import check_fallback
from ahq.evals.gate import RemoteRun, run_gate
from ahq.evals.retrieval import RetrievalReport, chart_svg, evaluate, load_questions
from ahq.evals.safety import DATASET as SAFETY_DATASET
from ahq.evals.safety import SafetyReport, SafetyResult, run_safety
from ahq.evals.scenarios import ScenarioTrial, check_scenario
from ahq.evals.tau3 import Tau3Report, TrialResult, run_tau3
from ahq.grading import Split, load_safety_cases, load_split, load_tasks
from ahq.mcp_servers import mint_token
from ahq.ports import EmbeddingTarget
from ahq.retail import canonical_hash, load_snapshot
from ahq.retrieval import (
    KB,
    KB_BASELINE,
    KB_PENDING,
    HybridRetriever,
    KbDocument,
    KnowledgeBase,
    ServerBm25,
    collection_stats,
    ingest,
    load_documents,
    restore_baseline,
)
from ahq.settings import REPO_ROOT, TAU3_VERSION, Settings, get_settings
from ahq.sim.control import SimControl
from ahq.sim.generate import ReviewRecord, TicketRecord, fill_embeddings, generate_history
from ahq.sim.generate.writer import Written, draft_reviews, draft_tickets, write_reviews, write_tickets
from ahq.sim.report import RunReport, report_run
from ahq.sim.seed import SeedReport, seed_world
from ahq.sim.tick import SimDeps

app = typer.Typer(no_args_is_help=True, help="AHQ command-line tools.")
OFFLINE_RECORDING = REPO_ROOT / "data" / "recordings" / "offline-day.json.gz"
db_app = typer.Typer(no_args_is_help=True, help="Database schema, seed data and row embeddings.")
kb_app = typer.Typer(no_args_is_help=True, help="The knowledge base in Qdrant.")
sim_app = typer.Typer(no_args_is_help=True, help="The simulator.")
eval_app = typer.Typer(
    no_args_is_help=True, help="Evaluations, run on demand. They spend money outside the mock profile."
)
world_app = typer.Typer(no_args_is_help=True, help="Written content for the world's past.")
agents_app = typer.Typer(no_args_is_help=True, help="Agent versions in the registry of the configured database.")
qa_app = typer.Typer(no_args_is_help=True, help="The QA reviewer's labels.")
app.add_typer(db_app, name="db")
app.add_typer(agents_app, name="agents")
app.add_typer(qa_app, name="qa")
app.add_typer(world_app, name="world")
app.add_typer(kb_app, name="kb")
app.add_typer(sim_app, name="sim")
app.add_typer(eval_app, name="eval")


def _embedding_key(settings: Settings) -> str:
    return "hashed-words" if settings.model_profile == "mock" else load_model_catalog().embeddings.id


def _direct_url(url: str | None) -> str:
    if url:
        return url
    settings = get_settings()
    configured = settings.database_url_unpooled or settings.database_url
    if configured is None:
        raise typer.BadParameter("set DATABASE_URL_UNPOOLED or pass --url")
    return configured.get_secret_value()


@db_app.command("migrate")
def migrate(url: Annotated[str | None, typer.Option(help="Direct (unpooled) Postgres URL.")] = None) -> None:
    """Apply every migration, then create LangGraph's checkpoint tables."""
    upgrade(_direct_url(url))
    typer.echo("database is up to date")


@db_app.command("clear-activity")
def db_clear_activity(
    url: Annotated[str | None, typer.Option(help="Direct (unpooled) Postgres URL.")] = None,
    versions: Annotated[
        bool,
        typer.Option(help="Also clear the agent versions; the api seeds version 1 from the code at its next start."),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Clear without asking first.")] = False,
) -> None:
    """Clear every record of what the team did, keeping the store, its history, the baseline, recorded days and
    settings, and put the knowledge base back as its articles were last ingested, dropping every draft waiting. The
    Data page of the control room's admin section does the same."""
    settings = get_settings()

    async def run() -> None:
        engine = make_engine(_direct_url(url))
        try:
            counts = await activity_counts(engine, versions=versions)
            for table, rows in counts.items():
                typer.echo(f"{table}: {rows} rows")
            if not yes:
                typer.confirm("Clear them all?", abort=True)
            await PgActivityStore(engine).clear(versions=versions)
        finally:
            await engine.dispose()
        if settings.qdrant_url is not None:
            store = make_vector_store(settings)
            try:
                passages = await restore_baseline(store)
            finally:
                await store.close()
            if passages is None:
                typer.echo(f"{KB}: no baseline yet; run `ahq kb ingest` to rebuild it from its files")
            else:
                typer.echo(f"{KB}: back to {passages} passages as last ingested; {KB_PENDING}: emptied")

    asyncio.run(run())
    typer.echo("activity cleared")


@db_app.command("seed")
def seed(
    url: Annotated[str | None, typer.Option(help="Postgres URL (default: the direct URL).")] = None,
    world_seed: Annotated[int, typer.Option("--seed", help="Seed for the generated history.")] = 7,
) -> None:
    """Replace the store with τ³-bench retail's data and generate the world around it."""
    settings = get_settings()
    store = load_snapshot(settings.data_dir / "tau3" / TAU3_VERSION / "db.json")

    async def run() -> SeedReport:
        engine = make_engine(_direct_url(url))
        try:
            sessions = make_sessionmaker(engine)
            report = await seed_world(
                PgRetailRepo(sessions),
                PgWorldRepo(sessions),
                store,
                load_world_config(),
                seed=world_seed,
                content_dir=settings.data_dir / "generated",
            )
            await PgBaseline(sessions).capture()
            return report
        finally:
            await engine.dispose()

    report = asyncio.run(run())
    typer.echo(", ".join(f"{count} {name.replace('_', ' ')}" for name, count in report.model_dump().items()))


@db_app.command("embed")
def embed(
    url: Annotated[str | None, typer.Option(help="Postgres URL (default: the direct URL).")] = None,
    cache: Annotated[Path | None, typer.Option(help="Local cache of embeddings (default: data/cache).")] = None,
) -> None:
    """Embed reviews and ticket messages that have no embedding yet, then update the simulator's baseline."""
    settings = get_settings()
    catalog = load_model_catalog()
    cache_path = cache or settings.data_dir / "cache" / "embeddings.sqlite"

    async def run() -> dict[EmbeddingTarget, int]:
        engine = make_engine(_direct_url(url))
        try:
            async with open_embedder(settings, catalog) as embedder:
                model = _embedding_key(settings)
                cached = CachingEmbedder(embedder, cache_path, model=model)
                try:
                    sessions = make_sessionmaker(engine)
                    counts = await fill_embeddings(PgWorldRepo(sessions), cached)
                    await PgBaseline(sessions).capture()
                    return counts
                finally:
                    cached.close()
        finally:
            await engine.dispose()

    counts = asyncio.run(run())
    typer.echo(", ".join(f"{count} {target.replace('_', ' ')}" for target, count in counts.items()) + " embedded")


@kb_app.command("ingest")
def kb_ingest() -> None:
    """Rebuild the `kb` collection from the articles in `kb/`, and `kb_baseline` as a copy that clearing the activity
    restores, then publish again every draft people approved, and create an empty `kb_pending` if needed."""
    settings = get_settings()
    if settings.qdrant_url is None:
        raise typer.BadParameter("QDRANT_URL is not set")
    documents = load_documents(settings.kb_dir)

    async def run() -> tuple[int, int]:
        store = make_vector_store(settings)
        try:
            async with open_embedder(settings, load_model_catalog()) as embedder:
                chunks = len(await ingest(store, embedder, ServerBm25(), documents))
                approved = await _approved_drafts(settings)
                knowledge = KnowledgeBase(store, embedder, ServerBm25())
                for document in approved:
                    await knowledge.publish(document, document.effective_date)
                return chunks, len(approved)
        finally:
            await store.close()

    chunks, approved = asyncio.run(run())
    typer.echo(f"ingested {len(documents)} articles as {chunks} chunks into {KB} and {KB_BASELINE}")
    typer.echo(f"published {approved} approved drafts again")


async def _approved_drafts(settings: Settings) -> list[KbDocument]:
    if settings.database_url is None:
        return []
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        drafts = await PgTeamRecords(make_sessionmaker(engine)).drafts("published")
    finally:
        await engine.dispose()
    documents = [KbDocument.model_validate(draft.document) for draft in drafts]
    return sorted(documents, key=lambda document: (document.effective_date, document.version))


@kb_app.command("stats")
def kb_stats() -> None:
    """Show what the knowledge base collections hold."""
    settings = get_settings()

    async def run() -> list[str]:
        store = make_vector_store(settings)
        try:
            lines = []
            for name in (KB, KB_PENDING, KB_BASELINE):
                stats = await collection_stats(store, name)
                if stats is None:
                    lines.append(f"{name}: missing")
                    continue
                vectors = " and ".join(v for v, present in (("dense", stats.dense), ("bm25", stats.sparse)) if present)
                lines.append(f"{name}: {stats.points} points, {vectors or 'no'} vectors")
            return lines
        finally:
            await store.close()

    typer.echo("\n".join(asyncio.run(run())))


class ContentKind(StrEnum):
    REVIEWS = "reviews"
    TICKETS = "tickets"


@world_app.command("write")
def world_write(
    kind: Annotated[ContentKind, typer.Argument(help="What to write.")],
    count: Annotated[int, typer.Option(help="How many to write.")] = 300,
    max_usd: Annotated[float, typer.Option(help="Stop once the calls cost this much.")] = 2.0,
    content_seed: Annotated[int, typer.Option("--seed", help="Seed for the facts.")] = 7,
) -> None:
    """Draft facts from the store and have the profile's `writer` model word them into `data/generated/`."""
    settings = get_settings()
    if settings.model_profile == "mock":
        raise typer.BadParameter("the mock profile has no real writer; set AHQ_MODEL_PROFILE to low, medium or high")
    catalog = load_model_catalog()
    world = load_world_config()
    store = load_snapshot(settings.data_dir / "tau3" / TAU3_VERSION / "db.json")
    models = make_chat_models(settings, catalog)

    async def run() -> Written[ReviewRecord] | Written[TicketRecord]:
        if kind is ContentKind.REVIEWS:
            return await write_reviews(
                models, draft_reviews(store, world, count=count, seed=content_seed), max_usd=max_usd
            )
        shipments = generate_history(store, world, content_seed).shipments
        seeds = draft_tickets(store, world, shipments, count=count, seed=content_seed)
        return await write_tickets(models, seeds, max_usd=max_usd, seed=content_seed)

    written = asyncio.run(run())
    path = settings.data_dir / "generated" / f"{kind.value}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(record.model_dump_json() + "\n" for record in written.records))
    note = ", stopped at the spend cap" if written.stopped_at_cap else ""
    typer.echo(
        f"wrote {len(written.records)} {kind.value} to {path} with {models.model_key('writer')} "
        f"for ${written.spent_usd:.4f}{note}"
    )


@sim_app.command("run")
def sim_run(
    scenario: Annotated[str, typer.Option(help="Scenario to play.")] = "normal-day",
    run_seed: Annotated[int, typer.Option("--seed", help="Seed for the day's script.")] = 7,
    url: Annotated[str | None, typer.Option(help="Postgres URL (default: the direct URL).")] = None,
) -> None:
    """Reset the store and play a whole day now, tick after tick with no delays. Prints a fingerprint of the run."""

    async def run() -> RunReport:
        engine = make_engine(_direct_url(url))
        try:
            sessions = make_sessionmaker(engine)
            deps = _sim_deps(sessions)
            cursor = await deps.events.last_id()
            control = SimControl(deps, PgBaseline(sessions), queue=None)
            started = await control.start(scenario, seed=run_seed, schedule=False)
            await control.drive(started.run_id)
            events = await deps.events.read_after(cursor, limit=1_000_000)
            return report_run(events, canonical_hash(await deps.retail.snapshot()))
        finally:
            await engine.dispose()

    report = asyncio.run(run())
    typer.echo(", ".join(f"{count} {kind}" for kind, count in report.counts.items()))
    typer.echo(f"events {report.events_digest}")
    typer.echo(f"store  {report.store_hash}")


@sim_app.command("reset")
def sim_reset(url: Annotated[str | None, typer.Option(help="Postgres URL (default: the direct URL).")] = None) -> None:
    """Stop any active run and put the store and world back to the baseline."""

    async def run() -> None:
        engine = make_engine(_direct_url(url))
        try:
            sessions = make_sessionmaker(engine)
            await SimControl(_sim_deps(sessions), PgBaseline(sessions), queue=None).reset()
        finally:
            await engine.dispose()

    asyncio.run(run())
    typer.echo("store and world reset to the baseline")


@sim_app.command("export")
def sim_export(
    recording: Annotated[str, typer.Option(help="The published recording to save, such as rec_3f2a9c.")],
    base_url: Annotated[str, typer.Option(help="The api to read it from.")] = "http://localhost:8000",
    out: Annotated[Path, typer.Option(help="Where to write the compressed bundle.")] = OFFLINE_RECORDING,
) -> None:
    """Save a published recorded day, compressed, read from an api's public endpoint. Reads only. The offline api
    publishes data/recordings/offline-day.json.gz at startup, so visitors to a local control room have a day to
    watch."""
    response = httpx.get(f"{base_url.rstrip('/')}/api/recordings/{recording}", timeout=300.0)
    response.raise_for_status()
    bundle = response.json()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(response.content, compresslevel=9, mtime=0))
    runs = len(bundle["runs"])
    typer.echo(f"{len(bundle['events'])} events, {runs} work items, {out.stat().st_size / 1e6:.2f} MB: {out}")


@sim_app.command("check")
def sim_check(
    scenario: Annotated[str, typer.Option(help="Scenario to play and grade.")] = "carrier-delay",
    run_seed: Annotated[int, typer.Option("--seed", help="Seed of the first trial; each trial adds one.")] = 7,
    trials: Annotated[int, typer.Option(min=1, help="How many days to play.")] = 1,
    profile: Annotated[ProfileName, typer.Option(help="Model profile.")] = "low",
    max_usd: Annotated[float, typer.Option(help="Start no new trial once spend reaches this.")] = 0.50,
    out: Annotated[Path | None, typer.Option(help="Report file (default: evals/results/).")] = None,
) -> None:
    """Play a scenario's day with alerts going to the agents, on the local database, and check what the team filed.
    Resets the store to its baseline first."""
    settings = get_settings().model_copy(update={"model_profile": profile})

    def show(trial: ScenarioTrial) -> None:
        typer.echo(
            f"seed {trial.seed}: {'pass' if trial.passed else 'fail'}  {trial.alerts} alerts, "
            f"{trial.work_items} work items, ${trial.cost_usd:.4f}, {trial.seconds:.0f}s"
            + (f"  {trial.error}" if trial.error else "")
        )
        for expectation in trial.expectations:
            typer.echo(f"  {'met' if expectation.met else 'missed'}: {expectation.name} ({expectation.detail})")

    report = asyncio.run(
        check_scenario(settings, scenario, seed=run_seed, trials=trials, max_usd=max_usd, progress=show)
    )
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    path = out or REPO_ROOT / "evals" / "results" / f"scenario-{scenario}-{profile}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    note = " (stopped at the spend cap)" if report.stopped_at_cap else ""
    typer.echo(f"passed {report.pass_rate:.0%} of {len(report.trials)} trials; ${report.cost_usd:.4f}{note}; {path}")


def _sim_deps(sessions: async_sessionmaker[AsyncSession]) -> SimDeps:
    clock = WallClock()
    return SimDeps(
        runs=PgSimStore(sessions, clock),
        retail=PgRetailRepo(sessions),
        world=PgWorldRepo(sessions),
        events=PgEventLog(sessions),
        clock=clock,
        config=load_world_config(),
    )


@app.command("charts")
def charts(
    tau3: Annotated[list[Path], typer.Option(help="τ³ reports to merge, in order; each task's trials add up.")],
    safety_on: Annotated[Path, typer.Option(help="The safety suite's report with the input check on.")],
    safety_off: Annotated[Path, typer.Option(help="The safety suite's report with the input check off.")],
    out: Annotated[Path, typer.Option(help="Where the charts go.")] = REPO_ROOT / "docs" / "img",
) -> None:
    """Draw the README's charts from eval reports: pass^k on τ³ retail, and the safety suite by layer."""
    reports = [Tau3Report.model_validate_json(path.read_text()) for path in tau3]
    outcomes = merge_trials(reports)
    profiles = {report.profile for report in reports}
    caption = f"τ³ retail, {len(outcomes)} test tasks, the {', '.join(sorted(profiles))} lineup"
    (out / "tau3-pass-k.svg").write_text(pass_k_svg(outcomes, caption=caption))
    on = SafetyReport.model_validate_json(safety_on.read_text())
    off = SafetyReport.model_validate_json(safety_off.read_text())
    (out / "safety-layers.svg").write_text(safety_svg(on, off))
    typer.echo(f"wrote {out / 'tau3-pass-k.svg'} and {out / 'safety-layers.svg'}")


@app.command("mcp-token")
def mcp_token(
    server: Annotated[str, typer.Option(help="MCP server name, for example `smoke`.")],
    subject: Annotated[str, typer.Option(help="Who the token is for: `operator`, `support` or `agents`.")] = "operator",
) -> None:
    """Print a bearer token for one MCP server, for example to connect Claude Desktop."""
    secret = get_settings().mcp_token_secret
    if secret is None:
        raise typer.BadParameter("AHQ_MCP_TOKEN_SECRET is not set")
    typer.echo(mint_token(secret.get_secret_value(), server, subject))


@app.command("openapi")
def openapi(output: Annotated[Path | None, typer.Option(help="Write to a file instead of stdout.")] = None) -> None:
    """Print the api's OpenAPI schema."""
    from ahq.api.factory import create_app

    schema = json.dumps(create_app().openapi(), indent=2, sort_keys=True)
    if output is None:
        typer.echo(schema)
    else:
        output.write_text(schema + "\n")


@eval_app.command("tau3")
def eval_tau3(
    split: Annotated[Split, typer.Option(help="τ³ split to draw tasks from.")] = "train",
    tasks: Annotated[int, typer.Option(help="How many tasks, from the start of the split.")] = 3,
    task_ids: Annotated[str | None, typer.Option(help="Comma-separated task ids, instead of --tasks.")] = None,
    trials: Annotated[int, typer.Option(min=1, help="Attempts per task; pass^k is reported up to k=trials.")] = 1,
    profile: Annotated[ProfileName, typer.Option(help="Model profile.")] = "low",
    max_usd: Annotated[float, typer.Option(help="Start no new trial once spend reaches this.")] = 0.50,
    concurrency: Annotated[int, typer.Option(min=1, help="Trials running at once.")] = 1,
    out: Annotated[Path | None, typer.Option(help="Report file (default: evals/results/).")] = None,
) -> None:
    """Run τ³ retail tasks against the team with simulated customers, and report pass^k and cost."""
    settings = get_settings().model_copy(update={"model_profile": profile})
    tau3 = settings.data_dir / "tau3" / TAU3_VERSION
    catalog = load_tasks(tau3 / "tasks.json")
    ids = task_ids.split(",") if task_ids else load_split(tau3 / "split_tasks.json", split)[:tasks]
    chosen = [catalog[task_id.strip()] for task_id in ids]
    store = load_snapshot(tau3 / "db.json")

    def show(result: TrialResult) -> None:
        mark = "pass" if result.reward == 1.0 else "fail"
        typer.echo(
            f"task {result.task_id:>3} trial {result.trial}: {mark}  db={result.db_match}  "
            f"{result.outcome}, {result.customer_turns} turns, {result.approvals} approvals, ${result.cost_usd:.4f}, "
            f"{result.cached_tokens} of {result.input_tokens} input tokens from cache"
            + (f"  {result.error}" if result.error else "")
        )

    report = asyncio.run(
        run_tau3(
            settings, chosen, store, split=split, trials=trials, max_usd=max_usd, concurrency=concurrency, progress=show
        )
    )
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    path = out or REPO_ROOT / "evals" / "results" / f"tau3-{profile}-{split}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    scores = ", ".join(f"pass^{k} {value:.2f}" for k, value in report.pass_k.items())
    note = " (stopped at the spend cap)" if report.stopped_at_cap else ""
    typer.echo(f"{scores or 'no complete tasks'}; ${report.cost_usd:.4f}{note}; report in {path}")


@eval_app.command("safety")
def eval_safety(
    profile: Annotated[ProfileName, typer.Option(help="Model profile.")] = "low",
    input_check: Annotated[
        bool, typer.Option(help="Run with the input check on; off shows what the rest stops.")
    ] = True,
    case_ids: Annotated[str | None, typer.Option(help="Comma-separated case ids, instead of every case.")] = None,
    max_usd: Annotated[float, typer.Option(help="Start no new case once spend reaches this.")] = 0.50,
    concurrency: Annotated[int, typer.Option(min=1, help="Cases running at once.")] = 4,
    out: Annotated[Path | None, typer.Option(help="Report file (default: evals/results/).")] = None,
) -> None:
    """Play attacks on the store, and look-alike controls, against the team, and report the share of attacks blocked,
    what blocked them, and false positives."""
    settings = get_settings().model_copy(update={"model_profile": profile})
    cases = load_safety_cases(SAFETY_DATASET)
    if case_ids:
        wanted = {case_id.strip() for case_id in case_ids.split(",")}
        cases = [case for case in cases if case.case_id in wanted]
    store = load_snapshot(settings.data_dir / "tau3" / TAU3_VERSION / "db.json")

    def show(result: SafetyResult) -> None:
        verdict = result.verdict
        mark = ("harmed: " + ", ".join(verdict.harms)) if verdict.harms else f"blocked by {verdict.stopped_by}"
        if not verdict.attempted:
            mark = "not attempted by the simulated customer"
        if not verdict.attack:
            mark = "flagged (false positive)" if verdict.flagged else "not flagged"
        typer.echo(
            f"{verdict.case_id:<22} {verdict.category:<12} {mark}; {result.outcome}, ${result.cost_usd:.4f}"
            + (f"  {result.error}" if result.error else "")
        )

    report = asyncio.run(
        run_safety(settings, cases, store, screen=input_check, max_usd=max_usd, concurrency=concurrency, progress=show)
    )
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    layers_on = "screen" if input_check else "noscreen"
    path = out or REPO_ROOT / "evals" / "results" / f"safety-{profile}-{layers_on}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    summary = report.summary
    rate = f"{summary.block_rate:.0%}" if summary.block_rate is not None else "n/a"
    layers = ", ".join(f"{layer} {count}" for layer, count in sorted(summary.by_layer.items()))
    typer.echo(f"blocked {summary.blocked} of {summary.attacks} attacks made ({rate}); by layer: {layers}")
    typer.echo(f"not attempted: {summary.not_attempted}")
    typer.echo(f"false positives: {summary.false_positives} of {summary.controls} controls")
    note = " (stopped at the spend cap)" if report.stopped_at_cap else ""
    typer.echo(f"${report.cost_usd:.4f}{note}; report in {path}")


@eval_app.command("fallback")
def eval_fallback(
    agent: Annotated[str, typer.Option(help="The agent whose fallback model to check.")] = "support",
    profile: Annotated[ProfileName, typer.Option(help="Model profile; the agent's model is the role's under it.")] = (
        "low"
    ),
    cases: Annotated[int | None, typer.Option(help="Cases per model (default: the gate's).")] = None,
    trials: Annotated[int, typer.Option(min=1, help="Trials per case.")] = 1,
    max_usd: Annotated[float, typer.Option(help="The most both runs together may spend.")] = 0.50,
    out: Annotated[Path | None, typer.Option(help="Report file (default: evals/results/).")] = None,
) -> None:
    """Run an agent's gate suite on its model and on that model's fallback, and judge the fallback as the gate
    judges a candidate."""
    settings = get_settings().model_copy(update={"model_profile": profile})
    report = asyncio.run(check_fallback(settings, agent, cases=cases, trials=trials, max_usd=max_usd))
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    path = out or REPO_ROOT / "evals" / "results" / f"fallback-{agent}-{profile}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2))
    for label, score in (("model", report.primary), ("fallback", report.backup)):
        name = report.model if label == "model" else report.fallback
        typer.echo(f"{label:<8} {name:<18} {score.metric} {score.score:.2f} over {score.cases}, ${score.cost_usd:.4f}")
    verdict = "passes" if report.passed else "fails: " + "; ".join(report.reasons)
    typer.echo(f"the fallback {verdict}; ${report.cost_usd:.4f}; report in {path}")


@eval_app.command("dispatcher")
def eval_dispatcher(
    profile: Annotated[ProfileName, typer.Option(help="Model profile.")] = "low",
    max_usd: Annotated[float, typer.Option(help="Route no new batch once spend reaches this.")] = 0.50,
    cases: Annotated[Path | None, typer.Option(help="Labeled cases (JSON lines).")] = None,
    rebuild: Annotated[bool, typer.Option(help="Rebuild the labeled cases from the store and templates.")] = False,
    out: Annotated[Path | None, typer.Option(help="Report file (default: evals/results/).")] = None,
) -> None:
    """Route labeled tickets, alerts and flags with the Dispatcher, and report accuracy and the confusion matrix."""
    settings = get_settings().model_copy(update={"model_profile": profile})
    path = cases or REPO_ROOT / "evals" / "datasets" / "dispatcher_routes.jsonl"
    if rebuild:
        write_cases(path, build_cases(load_snapshot(settings.data_dir / "tau3" / TAU3_VERSION / "db.json")))
    labeled = load_cases(path)
    report = asyncio.run(
        run_dispatcher_eval(
            make_chat_models(settings, load_model_catalog()),
            labeled,
            profile=profile,
            started_at=WallClock().now(),
            max_usd=max_usd,
        )
    )
    stamp = report.started_at.strftime("%Y%m%d-%H%M%S")
    target = out or REPO_ROOT / "evals" / "results" / f"dispatcher-{profile}-{stamp}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report.model_dump_json(indent=2))
    scores = report.scores
    typer.echo(f"accuracy {scores.accuracy:.1%} over {scores.cases} cases; split detection {scores.split_accuracy:.1%}")
    typer.echo("expected \\ chosen   " + "  ".join(f"{route:>8}" for route in scores.confusion))
    for truth, row in scores.confusion.items():
        typer.echo(f"{truth:>18}   " + "  ".join(f"{count:>8}" for count in row.values()))
    note = " (stopped at the spend cap)" if report.stopped_at_cap else ""
    typer.echo(f"${report.cost_usd:.4f}{note}; report in {target}")


@eval_app.command("retrieval")
def eval_retrieval(
    questions: Annotated[Path | None, typer.Option(help="Labeled questions (JSON lines).")] = None,
    chart: Annotated[bool, typer.Option(help="Write the mode comparison to docs/img/retrieval-modes.svg.")] = False,
    apply: Annotated[bool, typer.Option(help="Set the winning mode in config/retrieval.toml.")] = False,
) -> None:
    """Score dense, BM25, hybrid and hybrid plus reranker on labeled questions, in a temporary collection."""
    settings = get_settings()
    catalog = load_model_catalog()
    labeled = load_questions(questions or REPO_ROOT / "evals" / "datasets" / "retrieval_questions.jsonl")
    collection = f"kb_eval_{secrets.token_hex(4)}"

    async def run() -> RetrievalReport:
        store = make_vector_store(settings)
        try:
            async with (
                open_embedder(settings, catalog) as embedder,
                open_reranker(settings, catalog) as reranker,
            ):
                cached = CachingEmbedder(
                    embedder, settings.data_dir / "cache" / "embeddings.sqlite", model=_embedding_key(settings)
                )
                try:
                    sparse = make_sparse(settings)
                    documents = load_documents(settings.kb_dir)
                    await ingest(
                        store, cached, sparse, documents, collection=collection, pending=f"{collection}_pending"
                    )
                    config = load_retrieval_config()
                    retriever = HybridRetriever(store, cached, reranker, sparse, config, collection=collection)
                    return await evaluate(retriever, labeled)
                finally:
                    cached.close()
        finally:
            for name in (collection, f"{collection}_pending"):
                await store.delete_collection(name)
            await store.close()

    report = asyncio.run(run())
    for scores in report.modes:
        numbers = f"recall@5 {scores.recall_at_5:.3f}  MRR {scores.mrr:.3f}  nDCG@10 {scores.ndcg_at_10:.3f}"
        typer.echo(f"{scores.mode:>14}  {numbers}")
    typer.echo(f"best by nDCG@10: {report.best} ({report.questions} questions)")
    if chart:
        (REPO_ROOT / "docs" / "img" / "retrieval-modes.svg").write_text(chart_svg(report))
    if apply:
        path = CONFIG_DIR / "retrieval.toml"
        text = re.sub(r'^mode = "[a-z_]+"', f'mode = "{report.best}"', path.read_text(), count=1, flags=re.MULTILINE)
        path.write_text(text)


@eval_app.command("gate")
def eval_gate(
    candidate: Annotated[str | None, typer.Option(help="Candidate version, such as support@2, gated locally.")] = None,
    run_id: Annotated[str | None, typer.Option("--run", help="An eval run requested on a deployment.")] = None,
    api_url: Annotated[str | None, typer.Option(help="The deployment's api, for --run.")] = None,
    suite: Annotated[Suite | None, typer.Option(help="Suite to run instead of the agent's default.")] = None,
    cases: Annotated[int | None, typer.Option(min=1, help="τ³ tasks, routing cases or scenario days.")] = None,
    trials: Annotated[int | None, typer.Option(min=1, help="Attempts per case.")] = None,
    profile: Annotated[ProfileName | None, typer.Option(help="Model profile (default: the environment's).")] = None,
    max_usd: Annotated[float, typer.Option(help="Spending cap for both versions together.")] = 0.50,
) -> None:
    """Run the eval gate: a candidate against its agent's live version on the same cases."""
    settings = get_settings()
    if run_id is not None:
        token = os.environ.get("AHQ_OPERATOR_TOKEN")
        if api_url is None or not token:
            raise typer.BadParameter("--run needs --api-url and AHQ_OPERATOR_TOKEN")
        report = asyncio.run(_remote_gate(settings, api_url, token, run_id))
        typer.echo(report)
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a") as summary:
                summary.write(report)
        return
    if candidate is None:
        raise typer.BadParameter("give --candidate, or --run with --api-url")

    async def run() -> None:
        async with open_container(settings) as container:
            defaults = container.evals.default_params(candidate.partition("@")[0])
            params = GateParams(
                suite=suite or defaults.suite,
                profile=profile or settings.model_profile,
                cases=cases or defaults.cases,
                trials=trials or defaults.trials,
                max_usd=max_usd,
            )
            requested = await container.evals.request(candidate, by="cli", params=params, launch=False)
            await container.evals.started(requested.eval_run_id)
            baseline = await container.versions.get(requested.baseline_id)
            result = await run_gate(settings, requested, await container.versions.get(candidate), baseline)
            finished = await container.evals.finish(
                requested.eval_run_id, result.cases, result.summary, cost_usd=result.cost_usd
            )
        typer.echo(_gate_markdown(finished.eval_run_id, result.summary.model_dump(mode="json"), result.cost_usd))

    asyncio.run(run())


async def _remote_gate(settings: Settings, api_url: str, token: str, run_id: str) -> str:
    remote = RemoteRun(api_url, token, run_id)
    log_url = _actions_run_url()
    try:
        run, candidate, baseline = await remote.load()
        await remote.started(log_url)
        try:
            result = await run_gate(settings, run, candidate, baseline)
        except Exception as failure:
            await remote.report(None, error=f"{type(failure).__name__}: {failure}", url=log_url)
            raise
        await remote.report(result, url=log_url)
    finally:
        await remote.close()
    return _gate_markdown(run_id, result.summary.model_dump(mode="json"), result.cost_usd)


def _actions_run_url() -> str | None:
    names = ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
    server, repo, number = (os.environ.get(name) for name in names)
    return f"{server}/{repo}/actions/runs/{number}" if server and repo and number else None


def _gate_markdown(run_id: str, summary: dict[str, object], cost: float) -> str:
    rows = []
    for side in ("candidate", "baseline"):
        score = summary[side]
        assert isinstance(score, dict)
        rows.append(
            f"| {score['version_id']} | {score['metric']} | {score['score']} | {score['passed']}/{score['cases']} "
            f"| ${float(score['cost_usd']):.4f} |"
        )
    verdict = "passed" if summary["passed"] else "failed"
    reasons = summary.get("reasons") or []
    because = "".join(f"\n- {reason}" for reason in reasons) if isinstance(reasons, list) else ""
    return (
        f"### Eval gate {run_id}: {verdict}\n\n| Version | Metric | Score | Passed | Cost |\n|---|---|---|---|---|\n"
        + "\n".join(rows)
        + f"\n\nTotal ${cost:.4f}.{because}\n"
    )


@agents_app.command("list")
def agents_list() -> None:
    """List every version in the registry, newest first."""

    async def run() -> None:
        async with open_container(get_settings()) as container:
            for version in await container.versions.store.list():
                typer.echo(f"{version.version_id:<16} {version.status:<10} {version.created_by:<10} {version.note}")

    asyncio.run(run())


@agents_app.command("promote")
def agents_promote(
    version: Annotated[str, typer.Argument(help="The version to make live, such as support@2.")],
    reason: Annotated[str, typer.Option(help="Why, for the timeline.")],
    force: Annotated[bool, typer.Option(help="Promote a draft or evaluated version without a canary.")] = False,
) -> None:
    """Make a version live, retiring the live one. Without --force only a canary can be promoted."""

    async def run() -> None:
        async with open_container(get_settings()) as container:
            live = await container.versions.promote(version, by="cli", reason=reason, force=force)
            typer.echo(f"{live.version_id} is live")

    asyncio.run(run())


@qa_app.command("export-labels")
def qa_export_labels(
    api_url: Annotated[str | None, typer.Option(help="Read the labels from a deployment's api instead.")] = None,
    out: Annotated[Path | None, typer.Option(help="Where to write them.")] = None,
) -> None:
    """Write every QA label to evals/calibration/labels.jsonl, so the calibration set is versioned with the code."""

    async def read() -> list[dict[str, object]]:
        if api_url is not None:
            async with httpx.AsyncClient(base_url=api_url.rstrip("/"), timeout=30) as client:
                response = await client.get("/api/qa/labels")
                response.raise_for_status()
                return response.json()
        async with open_container(get_settings()) as container:
            return [label.model_dump(mode="json") for label in await container.quality.store.labels()]

    labels = asyncio.run(read())
    path = out or REPO_ROOT / "evals" / "calibration" / "labels.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(label, sort_keys=True) + "\n" for label in labels))
    typer.echo(f"wrote {len(labels)} labels to {path}")

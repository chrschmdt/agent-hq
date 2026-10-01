from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from ahq.adapters.clock import WallClock
from ahq.adapters.github import GitHubWorkflows
from ahq.adapters.langsmith import LangSmithTelemetry, NoopTelemetry
from ahq.adapters.mcp_client import HttpToolProvider, InProcessToolProvider
from ahq.adapters.memory import (
    MemoryApprovalStore,
    MemoryBaseline,
    MemoryEventLog,
    MemoryRecordingStore,
    MemorySimStore,
    MemoryTeamRecords,
    MemoryWorkStore,
    MemoryWorldRepo,
)
from ahq.adapters.memory_activity import MemoryActivityStore, MemoryCheckpoints
from ahq.adapters.memory_management import (
    MemoryControlStore,
    MemoryEvalStore,
    MemoryQualityStore,
    MemoryRunLedger,
    MemorySlots,
    MemoryVersionStore,
)
from ahq.adapters.openrouter import OpenRouterChatModels, OpenRouterEmbedder, OpenRouterReranker
from ahq.adapters.qdrant import QdrantHttp
from ahq.adapters.queue_inprocess import InProcessQueue
from ahq.adapters.queue_vercel import VercelQueue
from ahq.agents import SPECS, AgentBook, AgentSpec, CodeBook
from ahq.app.mcp import McpBundle, build_mcp, principals
from ahq.config import (
    ModelCatalog,
    ModelRole,
    ProfileName,
    QaConfig,
    load_approval_policy,
    load_budget_config,
    load_canary_config,
    load_guard_config,
    load_model_catalog,
    load_qa_config,
    load_retrieval_config,
    load_world_config,
)
from ahq.db.activity import PgActivityStore
from ahq.db.checkpointer import open_checkpointer
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import (
    PgApprovalStore,
    PgBaseline,
    PgControlStore,
    PgEvalStore,
    PgEventLog,
    PgQualityStore,
    PgReadOnlySql,
    PgRecordingStore,
    PgRetailRepo,
    PgRunLedger,
    PgSimStore,
    PgSlots,
    PgTeamRecords,
    PgVersionStore,
    PgWorkStore,
    PgWorldRepo,
)
from ahq.domain import ConfigurationError, WorkKind
from ahq.domain.retail import RetailSnapshot
from ahq.graphs import (
    SmokeDeps,
    TeamDeps,
    alert_start,
    build_smoke_graph,
    build_team_graph,
    flag_start,
    ticket_message,
    ticket_start,
    work_status,
)
from ahq.guardrails import InputCheck, ReplyCheck, StoreOwners, redact
from ahq.management import (
    ActivityDesk,
    CanaryWatch,
    EvalDesk,
    Limiter,
    ModelSwitch,
    QualityDesk,
    RunDesk,
    SwitchingChatModels,
    VersionRegistry,
)
from ahq.mcp_servers import mint_token
from ahq.ports import (
    ActivityStore,
    ApprovalStore,
    Baseline,
    ChatModels,
    Clock,
    ControlStore,
    Embedder,
    EvalLauncher,
    EvalStore,
    EventLog,
    QualityStore,
    Queue,
    ReadOnlySql,
    RecordingStore,
    Reranker,
    RetailRepo,
    RunLedger,
    SimStore,
    Slots,
    TeamRecords,
    Telemetry,
    TicketLog,
    ToolProvider,
    TraceKind,
    VectorStore,
    VersionStore,
    WorkStore,
    WorldRepo,
)
from ahq.retail import InMemoryRetailRepo, load_snapshot
from ahq.retrieval import HybridRetriever, KnowledgeBase, ServerBm25, SparseEncoder, ingest, load_documents
from ahq.runtime import (
    Commands,
    Conversations,
    GraphRegistry,
    GraphSpec,
    QaReviews,
    QueueLauncher,
    SegmentDeps,
    SegmentRunner,
    StoreTime,
    TeamDesk,
    Threads,
    build_handlers,
    fixed_input,
)
from ahq.settings import TAU3_VERSION, Settings
from ahq.sim.control import SimControl
from ahq.sim.customer import CustomerSimulator
from ahq.sim.seed import seed_world
from ahq.sim.tick import SimDeps
from ahq.testing import HashEmbedder, HashingSparse, OverlapReranker, RuleChatModels
from ahq.tools import DirectToolProvider, Principal, ReadCache, ToolDeps, ToolExecutor

Storage = Literal["memory", "postgres"]


@dataclass(frozen=True)
class Overrides:
    storage: Storage | None = None
    models: ChatModels | None = None
    clock: Clock | None = None
    duplicate_deliveries: bool = False
    store: RetailSnapshot | None = None
    embedder: Embedder | None = None
    flags_start_work: bool = True
    versions: Mapping[str, AgentSpec] | None = None
    review_runs: bool = True
    input_check: bool = True
    follow_model_choice: bool = False


@dataclass
class Container:
    settings: Settings
    catalog: ModelCatalog
    storage: Storage
    clock: Clock
    events: EventLog
    work: WorkStore
    approvals: ApprovalStore
    queue: Queue
    models: ChatModels
    model_switch: ModelSwitch
    tools: ToolProvider
    telemetry: Telemetry
    vector_store: VectorStore
    tickets: TicketLog
    executor: ToolExecutor
    mcp: McpBundle
    commands: Commands
    conversations: Conversations
    runner: SegmentRunner
    retail: RetailRepo
    world: WorldRepo
    sim_runs: SimStore
    baseline: Baseline
    sim: SimControl
    records: TeamRecords
    recordings: RecordingStore
    knowledge: KnowledgeBase
    desk: TeamDesk
    retriever: HybridRetriever
    embedder: Embedder
    analytics: ReadOnlySql | None
    versions: VersionRegistry
    limiter: Limiter
    ledger: RunLedger
    slots: Slots
    quality: QualityDesk
    canary: CanaryWatch
    runs: RunDesk
    evals: EvalDesk
    reviews: QaReviews
    threads: Threads
    activity: ActivityDesk
    inprocess_queue: InProcessQueue | None = field(default=None)


def _storage(settings: Settings, overrides: Overrides) -> Storage:
    if overrides.storage is not None:
        return overrides.storage
    return "postgres" if settings.database_url is not None else "memory"


def make_vector_store(settings: Settings) -> VectorStore:
    if settings.qdrant_url is None:
        from ahq.testing.qdrant import LocalVectorStore  # qdrant-client is a development dependency

        return LocalVectorStore()
    key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key is not None else None
    return QdrantHttp(settings.qdrant_url, key)


def make_chat_models(settings: Settings, catalog: ModelCatalog) -> ChatModels:
    return _models(settings, catalog, Overrides(), ModelSwitch(settings.model_profile, available=_playable(settings)))


def _playable(settings: Settings) -> list[ProfileName]:
    return ["mock"] if settings.openrouter_api_key is None else ["mock", "low", "medium", "high"]


def _models(
    settings: Settings,
    catalog: ModelCatalog,
    overrides: Overrides,
    switch: ModelSwitch,
    *,
    slots: Slots | None = None,
) -> ChatModels:
    if overrides.models is not None:
        return overrides.models
    roles = cast("dict[ModelRole, str]", settings.model_roles)
    served = catalog.forcing(roles) if roles else catalog
    key = settings.openrouter_api_key

    def build(profile: ProfileName) -> ChatModels:
        if profile == "mock":
            return RuleChatModels(pace=settings.fake_pace_seconds)
        if key is None:
            raise ConfigurationError(f"OPENROUTER_API_KEY is required for the {profile!r} profile")
        return OpenRouterChatModels(
            served,
            profile,
            api_key=key,
            base_url=settings.openrouter_base_url,
            calls=load_budget_config().calls,
            slots=slots,
        )

    build(switch.default)
    return SwitchingChatModels(switch, build)


@asynccontextmanager
async def open_embedder(
    settings: Settings, catalog: ModelCatalog, *, slots: Slots | None = None
) -> AsyncIterator[Embedder]:
    if settings.model_profile == "mock":
        yield HashEmbedder(catalog.embeddings.dimensions)
        return
    if settings.openrouter_api_key is None:
        raise ConfigurationError(f"OPENROUTER_API_KEY is required for the {settings.model_profile!r} profile")
    embedder = OpenRouterEmbedder(
        catalog.embeddings, api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url, slots=slots
    )
    try:
        yield embedder
    finally:
        await embedder.aclose()


def _tools(
    settings: Settings, mcp: McpBundle, executor: ToolExecutor, callers: Mapping[str, Principal]
) -> ToolProvider:
    if settings.tool_transport == "direct":
        return DirectToolProvider(executor, callers)
    if settings.tool_transport == "asgi":
        return InProcessToolProvider(mcp.servers)
    if settings.mcp_token_secret is None:
        raise ConfigurationError("AHQ_MCP_TOKEN_SECRET is required when AHQ_TOOL_TRANSPORT=http")
    secret = settings.mcp_token_secret.get_secret_value()
    return HttpToolProvider(
        settings.self_url, lambda server, subject: mint_token(secret, server, subject), headers=settings.self_headers
    )


@asynccontextmanager
async def open_reranker(
    settings: Settings, catalog: ModelCatalog, *, slots: Slots | None = None
) -> AsyncIterator[Reranker]:
    if settings.model_profile == "mock":
        yield OverlapReranker()
        return
    if settings.openrouter_api_key is None:
        raise ConfigurationError(f"OPENROUTER_API_KEY is required for the {settings.model_profile!r} profile")
    reranker = OpenRouterReranker(
        catalog.rerank, api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url, slots=slots
    )
    try:
        yield reranker
    finally:
        await reranker.aclose()


def make_sparse(settings: Settings) -> SparseEncoder:
    return ServerBm25() if settings.qdrant_url is not None else HashingSparse()


def _telemetry(settings: Settings) -> Telemetry:
    if settings.langsmith_api_key is None or settings.model_profile == "mock":
        return NoopTelemetry()
    return LangSmithTelemetry(
        api_key=settings.langsmith_api_key,
        project=settings.langsmith_project,
        sample_rate=settings.trace_sample_rate,
        redact=redact,
    )


def _book(settings: Settings, overrides: Overrides, registry: VersionRegistry) -> AgentBook:
    if overrides.versions is not None:
        return CodeBook({**SPECS, **overrides.versions})
    if settings.agent_versions == "code":
        return CodeBook()
    return registry


def _launcher(settings: Settings, queue: InProcessQueue | None) -> EvalLauncher | None:
    if settings.evals_run_on == "github":
        if settings.github_token is None or settings.github_repo is None:
            raise ConfigurationError("AHQ_GITHUB_TOKEN and AHQ_GITHUB_REPO are required for eval runs on GitHub")
        return GitHubWorkflows(settings.github_token, settings.github_repo, settings.github_ref)
    return QueueLauncher(queue) if queue is not None else None


def _qa_config(overrides: Overrides) -> QaConfig:
    config = load_qa_config()
    if overrides.review_runs:
        return config
    off = {"sample_rate": 0.0, "escalations": False, "rejected_approvals": False, "canary": False}
    return config.model_copy(update=off)


async def _seed_memory(settings: Settings, retail: RetailRepo, world: WorldRepo, baseline: Baseline) -> None:
    store = load_snapshot(settings.data_dir / "tau3" / TAU3_VERSION / "db.json")
    await seed_world(retail, world, store, load_world_config(), seed=7, content_dir=settings.data_dir / "generated")
    await baseline.capture()


def _graph_specs(smoke: SmokeDeps, team: TeamDeps) -> dict[WorkKind, GraphSpec]:
    return {
        WorkKind.SMOKE: GraphSpec(
            build=lambda: build_smoke_graph(smoke),
            initial_input=fixed_input(lambda item: {"work_item_id": item.id}),
            run_name="smoke",
            trace_kind=TraceKind.SMOKE,
        ),
        WorkKind.TICKET: GraphSpec(
            build=lambda: build_team_graph(team),
            initial_input=ticket_start(team.tickets),
            run_name="ticket",
            message_input=ticket_message(team.tickets),
            message_key="support_messages",
            finished_status=work_status,
        ),
        WorkKind.ALERT: GraphSpec(
            build=lambda: build_team_graph(team),
            initial_input=fixed_input(alert_start),
            run_name="alert",
            finished_status=work_status,
        ),
        WorkKind.FLAG: GraphSpec(
            build=lambda: build_team_graph(team),
            initial_input=fixed_input(flag_start),
            run_name="flag",
            finished_status=work_status,
        ),
    }


@asynccontextmanager
async def open_container(settings: Settings, *, overrides: Overrides | None = None) -> AsyncIterator[Container]:
    overrides = overrides or Overrides()
    catalog = load_model_catalog()
    clock = overrides.clock or WallClock()
    storage = _storage(settings, overrides)

    async with AsyncExitStack() as stack:
        events: EventLog
        work: WorkStore
        approvals: ApprovalStore
        checkpointer: BaseCheckpointSaver[Any]
        retail: RetailRepo
        world: WorldRepo
        tickets: TicketLog
        sim_runs: SimStore
        baseline: Baseline
        records: TeamRecords
        recordings: RecordingStore
        version_store: VersionStore
        ledger: RunLedger
        controls: ControlStore
        quality_store: QualityStore
        eval_store: EvalStore
        slots: Slots
        activity: ActivityStore
        analytics: ReadOnlySql | None = None
        if storage == "postgres":
            if settings.database_url is None:
                raise ConfigurationError("DATABASE_URL is required for postgres storage")
            url = settings.database_url.get_secret_value()
            engine = make_engine(url)
            stack.push_async_callback(engine.dispose)
            sessions = make_sessionmaker(engine)
            events, work, approvals = (
                PgEventLog(sessions),
                PgWorkStore(sessions, clock),
                PgApprovalStore(sessions, clock),
            )
            checkpointer = await stack.enter_async_context(open_checkpointer(url))
            pg_world = PgWorldRepo(sessions)
            retail, world, tickets = PgRetailRepo(sessions), pg_world, pg_world
            sim_runs, baseline = PgSimStore(sessions, clock), PgBaseline(sessions)
            records, analytics = PgTeamRecords(sessions), PgReadOnlySql(sessions)
            recordings = PgRecordingStore(sessions)
            version_store, ledger, controls = PgVersionStore(sessions), PgRunLedger(sessions), PgControlStore(sessions)
            quality_store, eval_store = PgQualityStore(sessions), PgEvalStore(sessions)
            slots = PgSlots(sessions)
            activity = PgActivityStore(engine)
        else:
            events, work, approvals = MemoryEventLog(clock), MemoryWorkStore(clock), MemoryApprovalStore(clock)
            checkpointer = InMemorySaver()
            retail = InMemoryRetailRepo(overrides.store or RetailSnapshot(products={}, users={}, orders={}))
            memory_world = MemoryWorldRepo()
            world, tickets = memory_world, memory_world
            sim_runs, baseline = MemorySimStore(clock), MemoryBaseline(retail, memory_world)
            records = MemoryTeamRecords()
            recordings = MemoryRecordingStore()
            version_store, ledger, controls = MemoryVersionStore(), MemoryRunLedger(), MemoryControlStore()
            quality_store, eval_store = MemoryQualityStore(), MemoryEvalStore()
            slots = MemorySlots()
            activity = MemoryActivityStore(
                [
                    events,
                    work,
                    approvals,
                    MemoryCheckpoints(checkpointer),
                    retail,
                    sim_runs,
                    records,
                    ledger,
                    controls,
                    quality_store,
                    eval_store,
                    slots,
                ],
                versions=version_store.clear_versions,
            )

        inprocess: InProcessQueue | None = None
        queue: Queue
        if settings.queue_backend == "vercel":
            queue = VercelQueue(region=settings.queue_region)
        else:
            inprocess = InProcessQueue(duplicate_deliveries=overrides.duplicate_deliveries)
            queue = inprocess

        switch = ModelSwitch(
            settings.model_profile,
            available=_playable(settings),
            store=controls if overrides.follow_model_choice else None,
            events=events,
            clock=clock,
        )
        if switch.switchable:
            await switch.refresh()
        models = _models(settings, catalog, overrides, switch, slots=slots)
        telemetry = _telemetry(settings)
        vector_store = make_vector_store(settings)
        stack.push_async_callback(vector_store.close)
        embedder = overrides.embedder or await stack.enter_async_context(open_embedder(settings, catalog, slots=slots))
        reranker = await stack.enter_async_context(open_reranker(settings, catalog, slots=slots))
        sparse = make_sparse(settings)
        if settings.qdrant_url is None and settings.kb_dir.is_dir():
            await ingest(vector_store, embedder, sparse, load_documents(settings.kb_dir))
        retriever = HybridRetriever(vector_store, embedder, reranker, sparse, load_retrieval_config())
        knowledge = KnowledgeBase(vector_store, embedder, sparse)
        reads = ReadCache(clock)
        executor = ToolExecutor(
            ToolDeps(
                retail=retail,
                retriever=retriever,
                approvals=approvals,
                clock=clock,
                analytics=analytics,
                embedder=embedder,
                knowledge=knowledge,
                records=records,
                world=world,
            ),
            context_key=settings.context_key,
            policy=load_approval_policy(),
            cache=reads,
        )
        callers = principals()
        mcp = build_mcp(settings, clock, executor, callers)
        tools = _tools(settings, mcp, executor, callers)
        smoke = SmokeDeps(models=models, tools=tools, events=events, clock=clock)
        commands = Commands(work=work, approvals=approvals, events=events, queue=queue, clock=clock, tickets=tickets)
        store_time = StoreTime(work=work, runs=sim_runs, clock=clock)
        desk = TeamDesk(
            commands=commands,
            records=records,
            knowledge=knowledge,
            events=events,
            clock=clock,
            start_flagged_work=overrides.flags_start_work,
            on_publish=reads.clear,
            store_time=store_time,
        )
        registry = VersionRegistry(version_store, events, clock, models=catalog.models.keys())
        limiter = Limiter(controls, events, clock, load_budget_config(), models.fallback)
        quality = QualityDesk(models, quality_store, limiter, events, clock, load_qa_config())
        canary = CanaryWatch(registry, ledger, quality, load_canary_config())
        runs = RunDesk(
            ledger,
            queue,
            registry,
            canary,
            limiter,
            clock,
            qa=_qa_config(overrides),
            budgets=load_budget_config(),
        )
        evals = EvalDesk(
            eval_store,
            registry,
            _launcher(settings, inprocess),
            events,
            clock,
            load_canary_config(),
            backend=settings.evals_run_on,
            profile=lambda: switch.current,
        )
        activity_desk = ActivityDesk(
            activity,
            knowledge=knowledge,
            versions=registry,
            work=work,
            runs=sim_runs,
            events=events,
            clock=clock,
            after=reads.clear,
        )
        conversations = Conversations(
            work=work,
            tickets=tickets,
            commands=commands,
            events=events,
            queue=queue,
            clock=clock,
            models=models,
            customer=CustomerSimulator(models),
            store_time=store_time,
        )
        guard = load_guard_config()
        team = TeamDeps(
            models=models,
            tools=tools,
            gate=executor,
            tickets=tickets,
            events=events,
            clock=clock,
            context_key=settings.context_key,
            records=records,
            after_reply=conversations.after_reply,
            raise_flag=desk.raise_flag,
            agents=_book(settings, overrides, registry),
            limits=limiter,
            after_run=runs.after_run,
            screen=InputCheck.of(guard.input) if overrides.input_check else None,
            store_time=store_time.simulated,
            replies=ReplyCheck(StoreOwners(retail), frozenset(guard.output.allowed_hosts)),
            read_cache=reads,
        )
        graphs = GraphRegistry(_graph_specs(smoke, team), checkpointer)
        runner = SegmentRunner(
            SegmentDeps(
                work=work,
                approvals=approvals,
                events=events,
                queue=queue,
                graphs=graphs,
                telemetry=telemetry,
                clock=clock,
                budget_seconds=settings.segment_budget_s,
                after_failure=runs.after_failure,
            )
        )
        reviews = QaReviews(work=work, graphs=graphs, quality=quality, canary=canary)
        sim_deps = SimDeps(
            runs=sim_runs,
            retail=retail,
            world=world,
            events=events,
            clock=clock,
            config=load_world_config(),
            desk=conversations,
            alerts=desk,
            deploys=registry,
            articles=desk,
        )
        sim = SimControl(sim_deps, baseline, queue)
        if storage == "memory" and settings.seed_memory:
            await _seed_memory(settings, retail, world, baseline)
        if settings.agent_versions == "registry" and overrides.versions is None:
            await registry.sync()
        if inprocess is not None:
            handlers = build_handlers(
                runner,
                sim,
                conversations,
                reviews if overrides.review_runs else None,
                before=switch.refresh if switch.switchable else None,
            )
            for topic, handler in handlers.items():
                inprocess.register(topic, handler)

        yield Container(
            settings=settings,
            catalog=catalog,
            storage=storage,
            clock=clock,
            events=events,
            work=work,
            approvals=approvals,
            queue=queue,
            models=models,
            model_switch=switch,
            tools=tools,
            telemetry=telemetry,
            vector_store=vector_store,
            tickets=tickets,
            executor=executor,
            mcp=mcp,
            commands=commands,
            conversations=conversations,
            runner=runner,
            retail=retail,
            world=world,
            sim_runs=sim_runs,
            baseline=baseline,
            sim=sim,
            records=records,
            recordings=recordings,
            knowledge=knowledge,
            desk=desk,
            retriever=retriever,
            embedder=embedder,
            analytics=analytics,
            versions=registry,
            limiter=limiter,
            ledger=ledger,
            slots=slots,
            quality=quality,
            canary=canary,
            runs=runs,
            evals=evals,
            reviews=reviews,
            threads=Threads(work=work, graphs=graphs),
            activity=activity_desk,
            inprocess_queue=inprocess,
        )

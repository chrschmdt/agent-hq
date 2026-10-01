from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryApprovalStore, MemoryEventLog, MemoryTeamRecords, MemoryWorldRepo
from ahq.agents import SPECS, AgentBook, CodeBook, principal_for
from ahq.config import ApprovalPolicy, load_retrieval_config
from ahq.domain import (
    AgentRun,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResume,
    KpiAlert,
    PatternFlag,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
    thread_for,
)
from ahq.domain.retail import RetailSnapshot
from ahq.domain.world import Ticket, TicketMessage
from ahq.graphs import StoreTimeHook, TeamDeps, alert_start, build_team_graph
from ahq.guardrails import InputCheck, ReplyCheck, StoreOwners
from ahq.ports import Limits, NoLimits, QueryRows
from ahq.retail import InMemoryRetailRepo
from ahq.retrieval import HybridRetriever, KnowledgeBase
from ahq.testing import FakeChatModels, HashEmbedder, HashingSparse, OverlapReranker
from ahq.testing.qdrant import LocalVectorStore
from ahq.tools import DirectToolProvider, ReadCache, ToolDeps, ToolExecutor
from tests.unit.retail.sample import sample_store

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
KEY = "test-context-key"
REFUND_LIMIT = 45.0
LATE_ROWS = QueryRows(columns=["carrier", "region", "late"], rows=[["northstar", "midwest", 31]])
ALERT = KpiAlert(
    metric="late_or_overdue_rate",
    segment={"carrier": "northstar", "region": "midwest"},
    window_hours=3,
    value=0.6,
    baseline=0.1,
    z_score=9.5,
    ratio=6.0,
    samples=40,
    detected_at=NOW,
)


def calls(*pairs: tuple[str, dict[str, Any]], start: int = 1) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{start + i}", "type": "tool_call"}
            for i, (name, args) in enumerate(pairs)
        ],
    )


def reply(text: str, *, citations: Sequence[str] = (), status: str = "awaiting_customer") -> AIMessage:
    return AIMessage(
        content=json.dumps({"reply": text, "citations": list(citations), "status": status, "summary": text})
    )


def answer(**fields: Any) -> AIMessage:
    return AIMessage(content=json.dumps(fields))


def route(to: str, *, split: Sequence[str] = ()) -> str:
    return json.dumps({"route": to, "priority": "normal", "reason": f"For {to}.", "split": list(split)})


def incident(next_owner: str = "insights", **fields: Any) -> AIMessage:
    report = {
        "title": "Northstar parcels late in the Midwest",
        "summary": "Northstar deliveries to the Midwest are days late since this morning.",
        "evidence": [{"query": "late shipments by carrier and region", "excerpt": "northstar midwest: 31 late"}],
        "suspected_cause": "A Northstar hub problem.",
        "affected": {"carrier": "northstar", "region": "midwest", "category": None, "item_id": None, "order_ids": []},
        "severity": "high",
        "recommended_action": "Tell affected customers and ask Northstar for an estimate.",
        "next": next_owner,
        "brief": "Please draft a customer notice about the delay." if next_owner != "none" else "",
    }
    return answer(**{**report, **fields})


def proposals(*items: Mapping[str, Any]) -> AIMessage:
    return answer(summary="One notice to draft.", proposals=[dict(item) for item in items])


def proposal(draft_id: str | None) -> dict[str, Any]:
    return {
        "kind": "kb_article",
        "title": "Tell Midwest customers about Northstar delays",
        "problem": "Customers do not know why parcels are late.",
        "evidence": ["late shipments by carrier and region"],
        "proposal": "Publish the drafted notice.",
        "expected_impact": "Fewer where-is-my-order tickets.",
        "risk": "Low.",
        "draft_id": draft_id,
    }


DRAFT = (
    "knowledge_draft_article",
    {
        "doc_id": "help-midwest-delays",
        "title": "Delays in the Midwest",
        "namespace": "shipping",
        "audience": "customer",
        "body": "# Delays in the Midwest\n\nSome parcels are late.\n\n## What to expect\n\nOne to three extra days.",
    },
)


class FixedSql:
    def __init__(self, rows: QueryRows) -> None:
        self.rows = rows
        self.queries: list[str] = []

    async def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryRows:
        self.queries.append(sql)
        return self.rows


def citing_first_passage(messages: Sequence[BaseMessage]) -> AIMessage:
    found = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "knowledge_search")
    first = json.loads(str(found.content))[0]["id"]
    return reply("Returns go back to the original payment method.", citations=[first])


class Harness:
    def __init__(
        self,
        store: LocalVectorStore,
        *,
        agents: AgentBook | None = None,
        limits: Limits | None = None,
        retail: RetailSnapshot | None = None,
        screen: InputCheck | None = None,
        check_replies: bool = False,
        store_time: StoreTimeHook | None = None,
        read_cache: ReadCache | None = None,
    ) -> None:
        self.clock = ManualClock(NOW)
        self.models = FakeChatModels()
        self.retail = InMemoryRetailRepo(retail or sample_store())
        self.world = MemoryWorldRepo()
        self.events = MemoryEventLog()
        self.approvals = MemoryApprovalStore(self.clock)
        self.records = MemoryTeamRecords()
        self.sql = FixedSql(LATE_ROWS)
        self.flags: list[tuple[str, PatternFlag, date]] = []
        retriever = HybridRetriever(store, HashEmbedder(), OverlapReranker(), HashingSparse(), load_retrieval_config())
        executor = ToolExecutor(
            ToolDeps(
                retail=self.retail,
                retriever=retriever,
                approvals=self.approvals,
                clock=self.clock,
                analytics=self.sql,
                embedder=HashEmbedder(),
                knowledge=KnowledgeBase(store, HashEmbedder(), HashingSparse()),
                records=self.records,
            ),
            context_key=KEY,
            policy=ApprovalPolicy(refund_limit_usd=REFUND_LIMIT),
        )
        callers = {spec.name: principal_for(spec) for spec in SPECS.values() if spec.tools}
        deps = TeamDeps(
            models=self.models,
            tools=DirectToolProvider(executor, callers),
            gate=executor,
            tickets=self.world,
            events=self.events,
            clock=self.clock,
            context_key=KEY,
            records=self.records,
            raise_flag=self.raise_flag,
            agents=agents or CodeBook(),
            limits=limits or NoLimits(),
            after_run=self.after_run,
            screen=screen,
            replies=ReplyCheck(StoreOwners(self.retail)) if check_replies else None,
            store_time=store_time,
            read_cache=read_cache,
        )
        self.runs: list[list[AgentRun]] = []
        self.graph = build_team_graph(deps).compile(checkpointer=InMemorySaver())
        self.config: Any = {"configurable": {"thread_id": "th_wi_1"}}

    async def after_run(self, runs: Sequence[AgentRun]) -> None:
        self.runs.append(list(runs))

    async def raise_flag(self, source: str, flag: PatternFlag, today: date) -> str:
        self.flags.append((source, flag, today))
        return "wi_flag"

    def alert(self) -> dict[str, Any]:
        item = WorkItem(
            id=WorkItemId("wi_1"),
            kind=WorkKind.ALERT,
            status=WorkStatus.NEW,
            thread_id=thread_for(WorkItemId("wi_1")),
            input={"alert": ALERT.model_dump(mode="json"), "today": "2026-06-15"},
            created_at=NOW,
            updated_at=NOW,
        )
        return alert_start(item)

    async def open(self, text: str, *, owner: str | None = "support") -> dict[str, Any]:
        message = TicketMessage(author="customer", body=text, created_at=NOW)
        await self.world.open_ticket(
            Ticket(
                ticket_id="tk_1",
                user_id="ada_1",
                intent="return_items",
                subject="Help",
                status="open",
                source="operator",
                created_at=NOW,
                messages=(message,),
            )
        )
        return {
            "work_item_id": "wi_1",
            "kind": "ticket",
            "ticket_id": "tk_1",
            "today": "2026-06-15",
            "brief": f"Subject: Help\n\n{text}",
            "owner": owner,
            "reply_position": 1,
            "support_messages": [HumanMessage(text, id="tk_1#0")],
        }

    async def run(self, graph_input: Any, *, thread: str = "th_wi_1") -> Any:
        config: Any = {"configurable": {"thread_id": thread}}
        return await self.graph.ainvoke(graph_input, config, version="v2", durability="sync")

    async def answer(self, output: Any, *decisions: ApprovalDecision) -> Command[Any]:
        resume: dict[str, Any] = {}
        for pending, decision in zip(output.interrupts, decisions, strict=True):
            approval = await self.approvals.open(
                WorkItemId("wi_1"), pending.id, ApprovalRequest.model_validate(pending.value)
            )
            await self.approvals.decide(approval.id, decision, "operator")
            resume[pending.id] = ApprovalResume(approval_id=approval.id, decision=decision).model_dump(mode="json")
        return Command(resume=resume)

    async def state(self) -> dict[str, Any]:
        return (await self.graph.aget_state(self.config)).values

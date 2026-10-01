from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta

from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.db.models import (
    AgentControlRow,
    AgentRunRow,
    AgentVersionRow,
    ModelHealthRow,
    ProviderSlotRow,
    SettingRow,
    SpendDailyRow,
)
from ahq.domain import (
    AgentControl,
    AgentRun,
    AgentVersion,
    ConflictError,
    ModelChoice,
    ModelHealth,
    NotFoundError,
    Serving,
    SpendLine,
    VersionConfig,
    VersionStatus,
)

MODEL_PROFILE = "model_profile"


def _version(row: AgentVersionRow) -> AgentVersion:
    return AgentVersion(
        version_id=row.version_id,
        agent=row.agent,
        number=row.number,
        status=VersionStatus(row.status),
        config=VersionConfig.model_validate(row.config),
        digest=row.digest,
        parent_id=row.parent_id,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
        status_at=row.status_at,
        status_reason=row.status_reason,
        canary_pct=row.canary_pct,
        eval_summary=row.eval_summary,
    )


class PgVersionStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, version: AgentVersion) -> AgentVersion:
        values = {
            **version.model_dump(mode="json", exclude={"status", "config", "created_at", "status_at"}),
            "status": version.status.value,
            "config": version.config.model_dump(mode="json"),
            "created_at": version.created_at,
            "status_at": version.status_at,
        }
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    insert(AgentVersionRow).values(values).on_conflict_do_nothing(index_elements=["agent", "digest"])
                )
                row = await session.scalar(
                    select(AgentVersionRow).where(
                        AgentVersionRow.agent == version.agent, AgentVersionRow.digest == version.digest
                    )
                )
        except IntegrityError as error:
            raise ConflictError(f"version {version.version_id} conflicts with a stored version") from error
        assert row is not None
        return _version(row)

    async def get(self, version_id: str) -> AgentVersion | None:
        async with self._sessions() as session:
            row = await session.get(AgentVersionRow, version_id)
        return None if row is None else _version(row)

    async def list(self, agent: str | None = None) -> list[AgentVersion]:
        query = select(AgentVersionRow).order_by(AgentVersionRow.created_at.desc(), AgentVersionRow.number.desc())
        if agent is not None:
            query = query.where(AgentVersionRow.agent == agent)
        async with self._sessions() as session:
            return [_version(row) for row in await session.scalars(query)]

    async def serving(self, agent: str) -> Serving:
        query = select(AgentVersionRow).where(
            AgentVersionRow.agent == agent, AgentVersionRow.status.in_(["live", "canary"])
        )
        async with self._sessions() as session:
            rows = {row.status: _version(row) for row in await session.scalars(query)}
        return Serving(live=rows.get("live"), canary=rows.get("canary"))

    async def next_number(self, agent: str) -> int:
        async with self._sessions() as session:
            highest = await session.scalar(
                select(AgentVersionRow.number)
                .where(AgentVersionRow.agent == agent)
                .order_by(AgentVersionRow.number.desc())
                .limit(1)
            )
        return (highest or 0) + 1

    async def set_status(
        self,
        version_id: str,
        status: VersionStatus,
        *,
        expected: Collection[VersionStatus],
        at: datetime,
        reason: str | None = None,
        canary_pct: int | None = None,
    ) -> AgentVersion:
        values: dict[str, object] = {"status": status.value, "status_at": at, "status_reason": reason}
        if canary_pct is not None:
            values["canary_pct"] = canary_pct
        try:
            async with self._sessions.begin() as session:
                row = await session.scalar(
                    update(AgentVersionRow)
                    .where(
                        AgentVersionRow.version_id == version_id,
                        AgentVersionRow.status.in_([s.value for s in expected]),
                    )
                    .values(values)
                    .returning(AgentVersionRow)
                )
                if row is None:
                    await self._explain(session, version_id)
        except IntegrityError as error:
            raise ConflictError(f"the agent of {version_id} already has a {status} version") from error
        assert row is not None
        return _version(row)

    async def promote(
        self, version_id: str, *, expected: Collection[VersionStatus], at: datetime, reason: str
    ) -> tuple[AgentVersion, AgentVersion | None]:
        async with self._sessions.begin() as session:
            chosen = await session.scalar(
                select(AgentVersionRow)
                .where(
                    AgentVersionRow.version_id == version_id,
                    AgentVersionRow.status.in_([s.value for s in expected]),
                )
                .with_for_update()
            )
            if chosen is None:
                await self._explain(session, version_id)
            assert chosen is not None
            retired_row = await session.scalar(
                update(AgentVersionRow)
                .where(AgentVersionRow.agent == chosen.agent, AgentVersionRow.status == "live")
                .values(status="retired", status_at=at, status_reason=f"{version_id} live")
                .returning(AgentVersionRow)
            )
            retired = None if retired_row is None else _version(retired_row)
            live_row = await session.scalar(
                update(AgentVersionRow)
                .where(AgentVersionRow.version_id == version_id)
                .values(status="live", status_at=at, status_reason=reason)
                .returning(AgentVersionRow)
            )
            assert live_row is not None
            return _version(live_row), retired

    async def set_eval_summary(self, version_id: str, summary: dict[str, JsonValue]) -> AgentVersion:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                update(AgentVersionRow)
                .where(AgentVersionRow.version_id == version_id)
                .values(eval_summary=summary)
                .returning(AgentVersionRow)
            )
        if row is None:
            raise NotFoundError(f"version {version_id} not found")
        return _version(row)

    @staticmethod
    async def _explain(session: AsyncSession, version_id: str) -> None:
        existing = await session.get(AgentVersionRow, version_id)
        if existing is None:
            raise NotFoundError(f"version {version_id} not found")
        raise ConflictError(f"version {version_id} is {existing.status}")


def _run(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        work_item_id=row.work_item_id,
        agent=row.agent,
        version_id=row.version_id,
        kind=row.kind,
        outcome=row.outcome,  # pyright: ignore[reportArgumentType]
        turns=row.turns,
        model_calls=row.model_calls,
        tool_calls=row.tool_calls,
        input_tokens=row.input_tokens,
        cached_tokens=row.cached_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        seconds=row.seconds,
        approvals=row.approvals,
        rejected_approvals=row.rejected_approvals,
        stop_reason=row.stop_reason,
        error=row.error,
        started_at=row.started_at,
        updated_at=row.updated_at,
    )


class PgRunLedger:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(self, runs: Sequence[AgentRun]) -> None:
        if not runs:
            return
        rows = [{**run.model_dump(), "finished": run.finished} for run in runs]
        statement = insert(AgentRunRow).values(rows)
        keys = ("work_item_id", "agent")
        replace = {column: statement.excluded[column] for column in rows[0] if column not in keys}
        async with self._sessions.begin() as session:
            await session.execute(statement.on_conflict_do_update(index_elements=list(keys), set_=replace))

    async def get(self, work_item_id: str, agent: str) -> AgentRun | None:
        async with self._sessions() as session:
            row = await session.get(AgentRunRow, (work_item_id, agent))
        return None if row is None else _run(row)

    async def runs(
        self,
        *,
        agent: str | None = None,
        version_id: str | None = None,
        finished: bool | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[AgentRun]:
        conditions = [
            condition
            for condition in (
                AgentRunRow.agent == agent if agent is not None else None,
                AgentRunRow.version_id == version_id if version_id is not None else None,
                AgentRunRow.finished == finished if finished is not None else None,
                AgentRunRow.updated_at >= since if since is not None else None,
            )
            if condition is not None
        ]
        query = (
            select(AgentRunRow)
            .where(*conditions)
            .order_by(AgentRunRow.updated_at.desc(), AgentRunRow.work_item_id.desc())
            .limit(limit)
        )
        async with self._sessions() as session:
            return [_run(row) for row in await session.scalars(query)]


class PgControlStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def controls(self) -> dict[str, AgentControl]:
        async with self._sessions() as session:
            rows = await session.scalars(select(AgentControlRow))
            return {
                row.agent: AgentControl(
                    agent=row.agent,
                    paused=row.paused,
                    reason=row.reason,
                    changed_by=row.changed_by,
                    changed_at=row.changed_at,
                )
                for row in rows
            }

    async def set_control(self, control: AgentControl) -> AgentControl:
        values = control.model_dump()
        statement = insert(AgentControlRow).values(values)
        async with self._sessions.begin() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["agent"], set_={key: statement.excluded[key] for key in values if key != "agent"}
                )
            )
        return control

    async def model_choice(self) -> ModelChoice | None:
        async with self._sessions() as session:
            row = await session.get(SettingRow, MODEL_PROFILE)
            if row is None:
                return None
            return ModelChoice(profile=row.value, changed_by=row.changed_by, changed_at=row.changed_at)

    async def set_model_choice(self, choice: ModelChoice) -> ModelChoice:
        values = {
            "key": MODEL_PROFILE,
            "value": choice.profile,
            "changed_by": choice.changed_by,
            "changed_at": choice.changed_at,
        }
        statement = insert(SettingRow).values(values)
        async with self._sessions.begin() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["key"], set_={key: statement.excluded[key] for key in values if key != "key"}
                )
            )
        return choice

    async def spend(self, day: date) -> list[SpendLine]:
        query = select(SpendDailyRow).where(SpendDailyRow.day == day).order_by(SpendDailyRow.agent, SpendDailyRow.model)
        async with self._sessions() as session:
            return [
                SpendLine(
                    day=row.day,
                    agent=row.agent,
                    model=row.model,
                    calls=row.calls,
                    errors=row.errors,
                    cost_usd=row.cost_usd,
                )
                for row in await session.scalars(query)
            ]

    async def add_spend(self, day: date, agent: str, model: str, *, cost_usd: float, ok: bool) -> None:
        errors = 0 if ok else 1
        statement = insert(SpendDailyRow).values(
            day=day, agent=agent, model=model, calls=1, errors=errors, cost_usd=cost_usd
        )
        async with self._sessions.begin() as session:
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["day", "agent", "model"],
                    set_={
                        "calls": SpendDailyRow.calls + 1,
                        "errors": SpendDailyRow.errors + errors,
                        "cost_usd": SpendDailyRow.cost_usd + cost_usd,
                    },
                )
            )

    async def health(self) -> dict[str, ModelHealth]:
        async with self._sessions() as session:
            return {row.model: _health(row) for row in await session.scalars(select(ModelHealthRow))}

    async def record_call(
        self, model: str, *, ok: bool, at: datetime, errors_to_open: int, cooldown: timedelta, error: str | None = None
    ) -> tuple[ModelHealth, bool]:
        async with self._sessions.begin() as session:
            if ok:
                row = await session.scalar(
                    update(ModelHealthRow)
                    .where(
                        ModelHealthRow.model == model,
                        (ModelHealthRow.consecutive_errors > 0) | ModelHealthRow.open_until.is_not(None),
                    )
                    .values(consecutive_errors=0, open_until=None, updated_at=at)
                    .returning(ModelHealthRow)
                )
                return (_health(row) if row else ModelHealth(model=model, consecutive_errors=0, updated_at=at)), False
            current = await session.scalar(
                select(ModelHealthRow).where(ModelHealthRow.model == model).with_for_update()
            )
            before = _health(current) if current else ModelHealth(model=model, consecutive_errors=0, updated_at=at)
            errors = before.consecutive_errors + 1
            opens = errors >= errors_to_open and not before.is_open(at)
            health = ModelHealth(
                model=model,
                consecutive_errors=errors,
                open_until=at + cooldown if opens else before.open_until,
                last_error=error,
                updated_at=at,
            )
            statement = insert(ModelHealthRow).values(health.model_dump())
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["model"],
                    set_={key: statement.excluded[key] for key in health.model_dump() if key != "model"},
                )
            )
            return health, opens


class PgSlots:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def acquire(self, provider: str, holder: str, *, limit: int, now: datetime, until: datetime) -> bool:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(ProviderSlotRow)
                .values([{"provider": provider, "slot": slot} for slot in range(limit)])
                .on_conflict_do_nothing()
            )
            free = (
                select(ProviderSlotRow.slot)
                .where(
                    ProviderSlotRow.provider == provider,
                    ProviderSlotRow.slot < limit,
                    ProviderSlotRow.held_until.is_(None) | (ProviderSlotRow.held_until <= now),
                )
                .order_by(ProviderSlotRow.slot)
                .limit(1)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )
            taken = await session.scalar(
                update(ProviderSlotRow)
                .where(ProviderSlotRow.provider == provider, ProviderSlotRow.slot == free)
                .values(holder=holder, held_until=until)
                .returning(ProviderSlotRow.slot)
            )
            return taken is not None

    async def release(self, provider: str, holder: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(ProviderSlotRow)
                .where(ProviderSlotRow.provider == provider, ProviderSlotRow.holder == holder)
                .values(holder=None, held_until=None)
            )


def _health(row: ModelHealthRow) -> ModelHealth:
    return ModelHealth(
        model=row.model,
        consecutive_errors=row.consecutive_errors,
        open_until=row.open_until,
        last_error=row.last_error,
        updated_at=row.updated_at,
    )

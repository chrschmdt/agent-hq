from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

from pydantic import JsonValue

from ahq.agents import SPECS, AgentSpec, agent_of, spec_from_version, validate_version, version_config
from ahq.domain import (
    AgentVersion,
    ConflictError,
    EventKind,
    InvalidRequest,
    NewEvent,
    NotFoundError,
    Serving,
    VersionConfig,
    VersionStatus,
    version_id_for,
)
from ahq.ports import Clock, EventLog, VersionStore
from ahq.scorecards import bucket
from ahq.tools import CATALOG, ToolSpec

SEEDED = "Seeded from code."
FROM_CODE = "Registered from a change in code."


class VersionRegistry:
    def __init__(
        self,
        store: VersionStore,
        events: EventLog,
        clock: Clock,
        *,
        models: Collection[str],
        specs: Mapping[str, AgentSpec] = SPECS,
        catalog: Mapping[str, ToolSpec] = CATALOG,
    ) -> None:
        self._store = store
        self._events = events
        self._clock = clock
        self._models = frozenset(models)
        self._specs = dict(specs)
        self._catalog = catalog
        self._cache: dict[str, AgentSpec] = {}

    @property
    def store(self) -> VersionStore:
        return self._store

    async def sync(self, specs: Iterable[AgentSpec] | None = None) -> list[AgentVersion]:
        created: list[AgentVersion] = []
        for spec in specs if specs is not None else self._specs.values():
            config = version_config(spec)
            stored = await self._store.list(spec.name)
            if any(version.digest == config.digest for version in stored):
                continue
            live = next((v for v in stored if v.status is VersionStatus.LIVE), None)
            status = VersionStatus.DRAFT if stored else VersionStatus.LIVE
            version = await self._create(
                spec.name,
                config,
                status=status,
                note=FROM_CODE if stored else SEEDED,
                by="code",
                parent_id=live.version_id if live else None,
            )
            if version is not None:
                created.append(version)
        return created

    async def pin(self, agent: str, work_item_id: str) -> AgentSpec:
        serving = await self._store.serving(agent)
        canary = serving.canary
        if canary is not None and serving.live is not None and bucket(work_item_id, agent, canary.canary_pct or 0):
            return self._spec_of(canary)
        if serving.live is not None:
            return self._spec_of(serving.live)
        return self._specs[agent]

    async def spec(self, version_id: str) -> AgentSpec:
        version = await self._store.get(version_id)
        if version is None:
            return self._specs[agent_of(version_id)]
        return self._spec_of(version)

    async def serving(self, agent: str) -> Serving:
        return await self._store.serving(agent)

    async def get(self, version_id: str) -> AgentVersion:
        version = await self._store.get(version_id)
        if version is None:
            raise NotFoundError(f"version {version_id} not found")
        return version

    async def draft(self, agent: str, config: VersionConfig, *, note: str, by: str) -> AgentVersion:
        base = self._specs.get(agent)
        if base is None:
            raise NotFoundError(f"agent {agent} not found")
        problems = validate_version(base, config, self._catalog, self._models)
        if problems:
            raise InvalidRequest("; ".join(problem.problem for problem in problems))
        live = (await self._store.serving(agent)).live
        version = await self._create(
            agent, config, status=VersionStatus.DRAFT, note=note, by=by, parent_id=live.version_id if live else None
        )
        if version is None:
            same = next(v for v in await self._store.list(agent) if v.digest == config.digest)
            raise ConflictError(f"{same.version_id} already has this configuration")
        return version

    async def record_eval(self, version_id: str, summary: dict[str, JsonValue], passed: bool) -> AgentVersion:
        version = await self._store.set_eval_summary(version_id, summary)
        if passed and version.status is VersionStatus.DRAFT:
            version = await self._store.set_status(
                version_id,
                VersionStatus.EVALUATED,
                expected={VersionStatus.DRAFT},
                at=self._clock.now(),
                reason="passed the eval gate",
            )
        await self._emit(EventKind.VERSION_EVALUATED, version, "eval", {"passed": passed})
        return version

    async def start_canary(self, version_id: str, *, pct: int, by: str, skip_gate: bool = False) -> AgentVersion:
        version = await self.get(version_id)
        if (await self._store.serving(version.agent)).live is None:
            raise ConflictError(f"{version.agent} has no live version to compare a canary with")
        expected = {VersionStatus.EVALUATED}
        if skip_gate:
            expected |= {VersionStatus.DRAFT, VersionStatus.RETIRED}
        skipped = skip_gate and version.status is not VersionStatus.EVALUATED
        reason = f"canary on {pct}% of new work" + (", without the eval gate" if skipped else "")
        started = await self._store.set_status(
            version_id, VersionStatus.CANARY, expected=expected, at=self._clock.now(), reason=reason, canary_pct=pct
        )
        await self._emit(EventKind.VERSION_CANARY_STARTED, started, by, {"pct": pct, "skipped_gate": skipped})
        return started

    async def canary_change(
        self, agent: str, *, changes: Mapping[str, JsonValue], pct: int, note: str, by: str
    ) -> AgentVersion:
        live = (await self._store.serving(agent)).live
        if live is None:
            raise ConflictError(f"{agent} has no live version to change")
        config = VersionConfig.model_validate({**live.config.model_dump(), **changes})
        same = [version for version in await self._store.list(agent) if version.digest == config.digest]
        version = same[0] if same else await self.draft(agent, config, note=note, by=by)
        return await self.start_canary(version.version_id, pct=pct, by=by, skip_gate=True)

    async def promote(self, version_id: str, *, by: str, reason: str, force: bool = False) -> AgentVersion:
        expected = {VersionStatus.CANARY}
        if force:
            expected |= {VersionStatus.DRAFT, VersionStatus.EVALUATED}
        live, retired = await self._store.promote(version_id, expected=expected, at=self._clock.now(), reason=reason)
        extra: dict[str, JsonValue] = {"reason": reason, "retired": retired.version_id if retired else None}
        await self._emit(EventKind.VERSION_PROMOTED, live, by, extra)
        return live

    async def roll_back(self, version_id: str, *, by: str, reasons: list[str]) -> AgentVersion:
        retired = await self._store.set_status(
            version_id,
            VersionStatus.RETIRED,
            expected={VersionStatus.CANARY},
            at=self._clock.now(),
            reason="rolled back: " + "; ".join(reasons),
        )
        await self._emit(EventKind.VERSION_ROLLED_BACK, retired, by, {"reasons": list(reasons)})
        return retired

    async def retire(self, version_id: str, *, by: str, reason: str) -> AgentVersion:
        retired = await self._store.set_status(
            version_id,
            VersionStatus.RETIRED,
            expected={VersionStatus.DRAFT, VersionStatus.EVALUATED},
            at=self._clock.now(),
            reason=reason,
        )
        await self._emit(EventKind.VERSION_RETIRED, retired, by, {"reason": reason})
        return retired

    async def _create(
        self,
        agent: str,
        config: VersionConfig,
        *,
        status: VersionStatus,
        note: str,
        by: str,
        parent_id: str | None,
    ) -> AgentVersion | None:
        now = self._clock.now()
        number = await self._store.next_number(agent)
        version = AgentVersion(
            version_id=version_id_for(agent, number),
            agent=agent,
            number=number,
            status=status,
            config=config,
            digest=config.digest,
            parent_id=parent_id,
            note=note,
            created_by=by,
            created_at=now,
            status_at=now,
            status_reason=note,
        )
        stored = await self._store.create(version)
        if stored.version_id != version.version_id:
            return None
        await self._emit(EventKind.VERSION_CREATED, stored, by, {"note": note, "parent_id": parent_id})
        return stored

    def _spec_of(self, version: AgentVersion) -> AgentSpec:
        key = f"{version.version_id}:{version.digest}"
        if key not in self._cache:
            self._cache[key] = spec_from_version(self._specs[version.agent], version)
        return self._cache[key]

    async def _emit(self, kind: EventKind, version: AgentVersion, by: str, extra: dict[str, JsonValue]) -> None:
        payload: dict[str, JsonValue] = {
            "agent": version.agent,
            "version_id": version.version_id,
            "status": version.status.value,
            **extra,
        }
        await self._events.append([NewEvent(kind=kind, occurred_at=self._clock.now(), actor=by, payload=payload)])

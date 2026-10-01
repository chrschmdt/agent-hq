from __future__ import annotations

from datetime import datetime

from ahq.adapters.clock import WallClock
from ahq.agents import SPECS
from ahq.config import load_canary_config, load_model_catalog
from ahq.domain import ConfigurationError, EvalCase, GateParams, NotFoundError, StrictModel, VersionScore
from ahq.evals.gate import SUITES
from ahq.settings import Settings


class FallbackReport(StrictModel):
    agent: str
    profile: str
    model: str
    fallback: str
    primary: VersionScore
    backup: VersionScore
    passed: bool
    reasons: list[str]
    cost_usd: float
    started_at: datetime
    cases: list[EvalCase]


async def check_fallback(
    settings: Settings, agent: str, *, cases: int | None = None, trials: int = 1, max_usd: float = 0.5
) -> FallbackReport:
    spec = SPECS.get(agent)
    policy = load_canary_config().gate
    suite = policy.suites.get(agent)
    if spec is None or suite is None:
        raise NotFoundError(f"no gate suite for agent {agent!r}")
    catalog = load_model_catalog()
    model, _ = catalog.resolve(settings.model_profile, spec.role, spec.model)
    fallback = catalog.models[model].fallback
    if fallback is None:
        raise ConfigurationError(f"{model} has no fallback")
    params = GateParams(
        suite=suite.suite,
        profile=settings.model_profile,
        cases=cases or suite.cases,
        trials=trials,
        max_usd=max_usd,
    )
    started_at = WallClock().now()
    run = SUITES[suite.suite]
    primary, primary_cases = await run(settings, params, spec, max_usd / 2)
    forced = settings.model_copy(update={"model_roles": {**settings.model_roles, spec.role: fallback}})
    backup, backup_cases = await run(forced, params, spec, max_usd / 2)
    reasons: list[str] = []
    if backup.cases == 0:
        reasons.append("the fallback completed no cases")
    elif primary.score - backup.score > policy.score_drop:
        reasons.append(f"{backup.metric} {backup.score:.2f} on {fallback} against {primary.score:.2f} on {model}")
    return FallbackReport(
        agent=agent,
        profile=settings.model_profile,
        model=model,
        fallback=fallback,
        primary=primary,
        backup=backup,
        passed=not reasons,
        reasons=reasons,
        cost_usd=round(primary.cost_usd + backup.cost_usd, 6),
        started_at=started_at,
        cases=primary_cases + backup_cases,
    )

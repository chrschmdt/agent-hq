from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import replace

from ahq.agents.prompts import CONTEXT_MARKER, PromptTemplate, fields
from ahq.agents.registry import CONTEXT_VALUES, validate_spec
from ahq.agents.types import AgentSpec, RunLimits, SpecProblem
from ahq.domain import AgentVersion, VersionConfig
from ahq.tools import ToolSpec


def version_config(spec: AgentSpec) -> VersionConfig:
    return VersionConfig(
        model=spec.model,
        prompt_stable=spec.prompt.stable,
        prompt_context=spec.prompt.context,
        tools=list(spec.tools),
        max_model_calls=spec.limits.max_model_calls,
        max_usd=spec.limits.max_usd,
    )


def spec_from_version(base: AgentSpec, version: AgentVersion) -> AgentSpec:
    config = version.config
    return replace(
        base,
        version=version.number,
        model=config.model,
        prompt=PromptTemplate(stable=config.prompt_stable, context=config.prompt_context),
        tools=tuple(config.tools),
        limits=RunLimits(max_model_calls=config.max_model_calls, max_usd=config.max_usd),
    )


def validate_version(
    base: AgentSpec, config: VersionConfig, catalog: Mapping[str, ToolSpec], models: Collection[str]
) -> list[SpecProblem]:
    problems: list[SpecProblem] = []
    name = base.name

    def problem(text: str) -> None:
        problems.append(SpecProblem(spec=name, problem=text))

    extra = sorted(set(config.tools) - set(base.tools))
    if extra:
        problem(f"tools not granted to {name}: {', '.join(extra)}")
    if config.model is not None and config.model not in models:
        problem(f"unknown model {config.model}")
    if fields(config.prompt_stable):
        problem(f"placeholders before '{CONTEXT_MARKER}': {sorted(fields(config.prompt_stable))}")
    if not config.prompt_context.startswith(CONTEXT_MARKER):
        problem(f"the context part must start with '{CONTEXT_MARKER}'")
    unknown = fields(config.prompt_context) - CONTEXT_VALUES
    if unknown:
        problem(f"unexpected prompt placeholders {sorted(unknown)}")
    if problems:
        return problems
    candidate = replace(
        base,
        prompt=PromptTemplate(stable=config.prompt_stable, context=config.prompt_context),
        tools=tuple(config.tools),
    )
    return validate_spec(candidate, catalog)

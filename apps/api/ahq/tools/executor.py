from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ahq.config import ApprovalPolicy
from ahq.domain import ApprovalId, ApprovalStatus, DuplicateCall, Effect, NotFoundError, ToolCallRecord, ToolResult
from ahq.tools.cache import ReadCache
from ahq.tools.catalog import CATALOG
from ahq.tools.context import decode_context
from ahq.tools.permissions import decide
from ahq.tools.types import (
    ActionFacts,
    CallContext,
    Decision,
    Deny,
    InvalidContext,
    Invocation,
    NeedsApproval,
    Principal,
    ToolDeps,
    ToolSpec,
)

CONTEXT_ARG = "ctx"


class ToolExecutor:
    def __init__(
        self, deps: ToolDeps, *, context_key: str, policy: ApprovalPolicy, cache: ReadCache | None = None
    ) -> None:
        self._deps = deps
        self._key = context_key
        self._policy = policy
        self._cache = cache

    async def call(self, principal: Principal, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        spec = CATALOG.get(name)
        if spec is None:
            return ToolResult.error(f"Tool '{name}' not found.")
        arguments = dict(arguments)
        token = arguments.pop(CONTEXT_ARG, None)
        try:
            args = spec.args.model_validate(arguments)
        except ValidationError as error:
            return ToolResult.error(f"Invalid arguments for {name}: {_summary(error)}")
        try:
            context = None if token is None else decode_context(str(token), self._key, self._deps.clock.now())
        except InvalidContext as error:
            return ToolResult.error(f"Refused: {error}.")
        if context is not None and context.subject != principal.subject:
            return ToolResult.error("Refused: the call context belongs to another caller.")
        facts = await spec.facts(args, self._deps) if spec.facts is not None else ActionFacts()
        match decide(principal, spec, facts, context, self._policy):
            case Deny(reason=reason):
                return ToolResult.error(reason)
            case NeedsApproval(reason=reason):
                return ToolResult.error(f"Approval required. {reason}")
            case _:
                pass
        if spec.needs_approval_record and context is not None and context.approval_id is not None:
            problem = await self._approval_problem(context, spec, args.model_dump(mode="json"))
            if problem is not None:
                return ToolResult.error(f"Refused: {problem}")
        if not spec.cacheable or self._cache is None:
            return await self._execute(spec, args, principal, context)
        day = context.as_of if context is not None else self._deps.clock.now().date()
        key = ReadCache.key(spec.name, args.model_dump(mode="json"), {"audience": principal.audience, "day": str(day)})
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._execute(spec, args, principal, context)
        self._cache.put(key, result)
        return result

    async def assess(
        self, principal: Principal, name: str, arguments: Mapping[str, Any], context: CallContext | None
    ) -> Decision:
        spec = CATALOG.get(name)
        if spec is None:
            return Deny(reason=f"Tool '{name}' not found.")
        try:
            args = spec.args.model_validate(dict(arguments))
        except ValidationError as error:
            return Deny(reason=f"Invalid arguments for {name}: {_summary(error)}")
        facts = await spec.facts(args, self._deps) if spec.facts is not None else ActionFacts()
        return decide(principal, spec, facts, context, self._policy)

    async def _execute(
        self, spec: ToolSpec, args: Any, principal: Principal, context: CallContext | None
    ) -> ToolResult:
        record = None
        if spec.effect is Effect.WRITE and context is not None:
            prior = await self._deps.retail.recorded_call(context.idempotency_key)
            if prior is not None:
                return ToolResult(output=prior.output)
            record = ToolCallRecord(
                key=context.idempotency_key,
                work_item_id=context.work_item_id,
                subject=principal.subject,
                tool=spec.name,
                arguments=args.model_dump(mode="json"),
                output="",
                approval_id=context.approval_id,
                recorded_at=self._deps.clock.now(),
            )
        try:
            return await spec.handler(args, Invocation(principal, context, record), self._deps)
        except DuplicateCall as duplicate:
            prior = await self._deps.retail.recorded_call(duplicate.key)
            if prior is None:
                raise
            return ToolResult(output=prior.output)

    async def _approval_problem(self, context: CallContext, spec: ToolSpec, arguments: dict[str, Any]) -> str | None:
        assert context.approval_id is not None
        try:
            approval = await self._deps.approvals.get(ApprovalId(context.approval_id))
        except NotFoundError:
            return "the approval does not exist."
        if approval.work_item_id != context.work_item_id:
            return "the approval belongs to other work."
        if approval.status not in {ApprovalStatus.APPROVED, ApprovalStatus.EDITED} or approval.decision is None:
            return "the action was not approved."
        approved = approval.decision.arguments if approval.status is ApprovalStatus.EDITED else None
        approved = approved if approved is not None else approval.request.arguments
        if approval.request.action != spec.name or approved != arguments:
            return "the approval was for a different action."
        return None


def _summary(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in error.errors())

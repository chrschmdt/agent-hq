from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from functools import cache
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from ahq.config import ModelRole, ProfileName
from ahq.domain import CallReport, ConflictError, EventKind, ModelChoice, NewEvent, Price, SystemPrompt
from ahq.ports import ChatModels, Clock, ControlStore, EventLog


class ModelSwitch:
    def __init__(
        self,
        default: ProfileName,
        *,
        available: Collection[ProfileName],
        store: ControlStore | None = None,
        events: EventLog | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._default: ProfileName = default
        self._available = frozenset(available)
        self._store = store
        self._events = events
        self._clock = clock
        self._current: ProfileName = default

    @property
    def current(self) -> ProfileName:
        return self._current

    @property
    def default(self) -> ProfileName:
        return self._default

    @property
    def available(self) -> frozenset[ProfileName]:
        return self._available

    @property
    def switchable(self) -> bool:
        return self._store is not None

    async def refresh(self) -> ProfileName:
        choice = await self.choice()
        profile = choice.profile if choice is not None else self._default
        self._current = profile if profile in self._available else self._default
        return self._current

    async def choice(self) -> ModelChoice | None:
        return await self._store.model_choice() if self._store is not None else None

    async def choose(self, profile: ProfileName, *, by: str) -> ModelChoice:
        if self._store is None or self._clock is None:
            raise ConflictError("this process plays one fixed model profile")
        if profile not in self._available:
            raise ConflictError(f"the {profile} profile needs OPENROUTER_API_KEY on this deployment")
        previous = self._current
        choice = await self._store.set_model_choice(
            ModelChoice(profile=profile, changed_by=by, changed_at=self._clock.now())
        )
        self._current = profile
        if self._events is not None:
            await self._events.append(
                [
                    NewEvent(
                        kind=EventKind.MODELS_SWITCHED,
                        occurred_at=choice.changed_at,
                        actor=by,
                        payload={"profile": profile, "previous": previous},
                    )
                ]
            )
        return choice


class SwitchingChatModels:
    def __init__(self, switch: ModelSwitch, build: Callable[[ProfileName], ChatModels]) -> None:
        self._switch = switch
        self._build = cache(build)

    def _active(self) -> ChatModels:
        return self._build(self._switch.current)

    def chat(self, role: ModelRole, model: str | None = None) -> BaseChatModel:
        return self._active().chat(role, model)

    def model_key(self, role: ModelRole, preferred: str | None = None) -> str:
        return self._active().model_key(role, preferred)

    def fallback(self, model: str) -> str | None:
        return self._active().fallback(model)

    def price(self, role: ModelRole, model: str | None = None) -> Price:
        return self._active().price(role, model)

    def report(self, message: BaseMessage) -> CallReport:
        return self._active().report(message)

    def agent_model(
        self,
        role: ModelRole,
        *,
        system: SystemPrompt,
        tools: Sequence[Mapping[str, Any]],
        reply: type[BaseModel],
        model: str | None = None,
    ) -> Runnable[Sequence[BaseMessage], BaseMessage]:
        return self._active().agent_model(role, system=system, tools=tools, reply=reply, model=model)

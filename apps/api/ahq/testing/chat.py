from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import BaseTool
from pydantic import BaseModel, PrivateAttr, SkipValidation

from ahq.adapters.openrouter.usage import usage_from_message
from ahq.config import ModelRole
from ahq.domain import CallReport, Price, SystemPrompt
from ahq.ports.models import prepend_system

Reply = AIMessage | str | Callable[[Sequence[BaseMessage]], AIMessage | str]

DEFAULT_USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


class ScriptedChatModel(BaseChatModel):
    replies: SkipValidation[list[Reply]]
    repeat_last: bool = True
    latency_seconds: float = 0.0
    _cursor: int = PrivateAttr(default=0)
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)
    _bound_tools: list[Any] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    @property
    def bound_tools(self) -> list[Any]:
        return self._bound_tools

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self._calls.append(list(messages))
        if self._cursor < len(self.replies):
            reply = self.replies[self._cursor]
            self._cursor += 1
        elif self.repeat_last and self.replies:
            reply = self.replies[-1]
        else:
            raise AssertionError("the script ran out of replies")
        if callable(reply):
            reply = reply(messages)
        message = AIMessage(content=reply) if isinstance(reply, str) else reply
        if message.usage_metadata is None:
            message = message.model_copy(update={"usage_metadata": DEFAULT_USAGE})
        return message

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.latency_seconds > 0:
            await asyncio.sleep(self.latency_seconds)
        return self._generate(messages, stop=stop, **kwargs)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        if tool_choice not in (None, "auto"):
            raise AssertionError("forced tool choice is not allowed; use native structured output")
        self._bound_tools = list(tools)
        return self

    def with_structured_output(
        self,
        schema: dict[str, Any] | type,
        *,
        method: str = "function_calling",
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, Any]:
        if method != "json_schema":
            raise AssertionError(f"structured output must use method='json_schema', got {method!r}")

        def read(message: BaseMessage) -> Any:
            data = json.loads(str(message.content))
            parsed = schema.model_validate(data) if isinstance(schema, type) and issubclass(schema, BaseModel) else data
            return {"raw": message, "parsed": parsed, "parsing_error": None} if include_raw else parsed

        def parse(value: LanguageModelInput) -> Any:
            return read(self.invoke(value))

        async def aparse(value: LanguageModelInput) -> Any:
            return read(await self.ainvoke(value))

        return RunnableLambda(parse, afunc=aparse)


class FakeChatModels:
    def __init__(self, scripts: Mapping[ModelRole, ScriptedChatModel] | None = None) -> None:
        self._models: dict[ModelRole, ScriptedChatModel] = dict(scripts or {})

    def script(self, role: ModelRole, *replies: Reply) -> ScriptedChatModel:
        model = ScriptedChatModel(replies=list(replies))
        self._models[role] = model
        return model

    def chat(self, role: ModelRole, model: str | None = None) -> BaseChatModel:
        if role not in self._models:
            self._models[role] = ScriptedChatModel(replies=[f"Hello from the {role} role."])
        return self._models[role]

    def model_key(self, role: ModelRole, preferred: str | None = None) -> str:
        return "fake"

    def fallback(self, model: str) -> str | None:
        return None

    def price(self, role: ModelRole, model: str | None = None) -> Price:
        return Price(input=0.0, output=0.0)

    def report(self, message: BaseMessage) -> CallReport:
        return CallReport(usage=usage_from_message(message), provider="scripted", billed_usd=0.0)

    def agent_model(
        self,
        role: ModelRole,
        *,
        system: SystemPrompt,
        tools: Sequence[Mapping[str, Any]],
        reply: type[BaseModel],
        model: str | None = None,
    ) -> Runnable[Sequence[BaseMessage], BaseMessage]:
        bound = self.chat(role).bind_tools([dict(tool) for tool in tools])
        return prepend_system(SystemMessage(system.text)) | bound

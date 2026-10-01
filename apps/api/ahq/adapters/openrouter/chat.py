from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import cache, cached_property
from typing import Any

import anthropic
import httpx2
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, SecretStr

from ahq.adapters.clock import WallClock
from ahq.adapters.openrouter.transport import GovernedTransport, Governor, provider_of
from ahq.adapters.openrouter.usage import report_from_message
from ahq.config import CallPolicy, ModelCatalog, ModelRole, ModelSpec, ProfileName, load_budget_config
from ahq.domain import CallReport, ConfigurationError, Price, SystemPrompt
from ahq.ports import Clock, Slots
from ahq.ports.models import prepend_system, reply_tool

APP_HEADERS = {"X-Title": "AHQ"}
TIMEOUT = httpx2.Timeout(300.0, connect=10.0)


class GovernedChatAnthropic(ChatAnthropic):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    transport: httpx2.AsyncBaseTransport | None = None

    @cached_property
    def _async_client(self) -> anthropic.AsyncClient:
        params = self._client_params
        http = httpx2.AsyncClient(base_url=params["base_url"], transport=self.transport, timeout=TIMEOUT)
        return anthropic.AsyncClient(**params, http_client=http)


class OpenRouterChatModels:
    def __init__(
        self,
        catalog: ModelCatalog,
        profile: ProfileName,
        *,
        api_key: SecretStr,
        base_url: str,
        calls: CallPolicy | None = None,
        slots: Slots | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._catalog = catalog
        self._profile: ProfileName = profile
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._calls = calls or load_budget_config().calls
        self._slots = slots
        self._clock = clock or WallClock()
        self._build = cache(self._build_uncached)
        self._transport = cache(self._transport_uncached)

    def chat(self, role: ModelRole, model: str | None = None) -> BaseChatModel:
        return self._build(model or self.model_key(role))

    def model_key(self, role: ModelRole, preferred: str | None = None) -> str:
        key, _ = self._catalog.resolve(self._profile, role, preferred)
        return key

    def fallback(self, model: str) -> str | None:
        return self._catalog.models[model].fallback

    def price(self, role: ModelRole, model: str | None = None) -> Price:
        spec = self._catalog.models[model or self.model_key(role)]
        return Price(input=spec.input, output=spec.output, cache_read=spec.cache_read, cache_write=spec.cache_write)

    def report(self, message: BaseMessage) -> CallReport:
        return report_from_message(message)

    def agent_model(
        self,
        role: ModelRole,
        *,
        system: SystemPrompt,
        tools: Sequence[Mapping[str, Any]],
        reply: type[BaseModel],
        model: str | None = None,
    ) -> Runnable[Sequence[BaseMessage], BaseMessage]:
        key = model or self.model_key(role)
        spec = self._catalog.models[key]
        chat = self._build(key)
        prompt: SystemMessage
        if spec.route == "openrouter-anthropic":
            output: dict[str, Any] = {}
            if spec.reply_format == "schema":
                output["format"] = {"type": "json_schema", "schema": reply.model_json_schema()}
            if spec.effort is not None:
                output["effort"] = spec.effort
            offered = [dict(tool) for tool in tools]
            if spec.reply_format == "tool":
                offered.append(reply_tool(reply))
            bound = chat.bind_tools(offered)
            if output:
                bound = bound.bind(output_config=output)
            if spec.reasoning is not None:
                bound = bound.bind(thinking={"type": spec.reasoning, "display": "summarized"})
            prompt = SystemMessage(
                content=[
                    {"type": "text", "text": system.stable, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": system.dynamic or " "},
                ]
            )
        else:
            bound = chat.bind_tools([dict(tool) for tool in tools])
            prompt = SystemMessage(content=system.text)
        return prepend_system(prompt) | bound

    def _build_uncached(self, key: str) -> BaseChatModel:
        spec = self._catalog.models[key]
        match spec.route:
            case "openrouter-anthropic":
                return self._anthropic(spec)
            case "openrouter-openai":
                return self._openai(spec)
            case "fake":
                raise ConfigurationError("fake models are only available under the mock profile")

    def _transport_uncached(self, provider: str) -> GovernedTransport:
        return GovernedTransport(Governor(provider, self._calls, self._clock, slots=self._slots))

    def _anthropic(self, spec: ModelSpec) -> BaseChatModel:
        key = self._api_key.get_secret_value()
        routing = {"provider": {"order": list(spec.providers), "allow_fallbacks": True}} if spec.providers else {}
        return GovernedChatAnthropic(
            model_name=spec.id,
            base_url=self._base_url,
            api_key=self._api_key,
            default_headers={**APP_HEADERS, "Authorization": f"Bearer {key}"},
            max_tokens_to_sample=spec.max_output_tokens,
            max_retries=0,
            timeout=None,
            stop=None,
            model_kwargs={"extra_body": routing} if routing else {},
            transport=self._transport(provider_of(spec.id)),
        )

    def _openai(self, spec: ModelSpec) -> BaseChatModel:
        return ChatOpenAI(
            model=spec.id,
            base_url=f"{self._base_url}/v1",
            api_key=self._api_key,
            default_headers=APP_HEADERS,
            max_retries=0,
            http_async_client=httpx2.AsyncClient(transport=self._transport(provider_of(spec.id)), timeout=TIMEOUT),
        )

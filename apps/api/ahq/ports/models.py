from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

from ahq.config import ModelRole
from ahq.domain import CallReport, Price, StrictModel, SystemPrompt

EmbeddingKind = Literal["query", "document"]


class RerankHit(StrictModel):
    index: int = Field(ge=0)
    score: float


class ChatModels(Protocol):
    def chat(self, role: ModelRole, model: str | None = None) -> BaseChatModel: ...

    def model_key(self, role: ModelRole, preferred: str | None = None) -> str: ...

    def fallback(self, model: str) -> str | None: ...

    def price(self, role: ModelRole, model: str | None = None) -> Price: ...

    def report(self, message: BaseMessage) -> CallReport: ...

    def agent_model(
        self,
        role: ModelRole,
        *,
        system: SystemPrompt,
        tools: Sequence[Mapping[str, Any]],
        reply: type[BaseModel],
        model: str | None = None,
    ) -> Runnable[Sequence[BaseMessage], BaseMessage]: ...


class Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: Sequence[str], kind: EmbeddingKind) -> list[list[float]]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[RerankHit]: ...


async def ask_typed[T: BaseModel](
    models: ChatModels,
    role: ModelRole,
    schema: type[T],
    messages: Sequence[BaseMessage],
    *,
    model: str | None = None,
) -> tuple[T, CallReport]:
    typed = models.chat(role, model).with_structured_output(schema, method="json_schema", include_raw=True)
    result = cast("dict[str, Any]", await typed.ainvoke(list(messages)))
    return schema.model_validate(result["parsed"]), models.report(result["raw"])


REPLY_TOOL = "reply"


def reply_tool(reply: type[BaseModel]) -> dict[str, Any]:
    schema = {key: value for key, value in reply.model_json_schema().items() if key not in {"title", "description"}}
    return {
        "type": "function",
        "function": {
            "name": REPLY_TOOL,
            "description": (
                "Give your reply and end your turn: its arguments are the JSON object your instructions describe. "
                "Call it alone, once you have what you need, including when you are asking the customer something."
            ),
            "parameters": schema,
        },
    }


def prepend_system(prompt: BaseMessage) -> Runnable[Sequence[BaseMessage], list[BaseMessage]]:
    def prepend(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        return [prompt, *messages]

    return RunnableLambda(prepend)

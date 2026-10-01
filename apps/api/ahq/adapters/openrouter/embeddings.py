from __future__ import annotations

from collections.abc import Sequence

import httpx
from pydantic import SecretStr

from ahq.adapters.clock import WallClock
from ahq.adapters.openrouter.chat import APP_HEADERS
from ahq.adapters.openrouter.transport import GovernedHttpxTransport, Governor, provider_of
from ahq.config import CallPolicy, EmbeddingSpec, load_budget_config
from ahq.ports import EmbeddingKind, Slots


class OpenRouterEmbedder:
    def __init__(
        self,
        spec: EmbeddingSpec,
        *,
        api_key: SecretStr,
        base_url: str,
        batch_size: int = 64,
        calls: CallPolicy | None = None,
        slots: Slots | None = None,
    ) -> None:
        self._spec = spec
        self._batch_size = batch_size
        governor = Governor(provider_of(spec.id), calls or load_budget_config().calls, WallClock(), slots=slots)
        transport = GovernedHttpxTransport(governor)
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/v1",
            headers={**APP_HEADERS, "Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=60.0,
            transport=transport,
        )

    @property
    def dimensions(self) -> int:
        return self._spec.dimensions

    async def embed(self, texts: Sequence[str], kind: EmbeddingKind) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            response = await self._client.post(
                "/embeddings",
                json={
                    "model": self._spec.id,
                    "input": batch,
                    "input_type": kind,
                    "dimensions": self._spec.dimensions,
                },
            )
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            vectors.extend(row["embedding"] for row in rows)
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()

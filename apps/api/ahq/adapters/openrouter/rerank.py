from __future__ import annotations

from collections.abc import Sequence

import httpx
from pydantic import SecretStr

from ahq.adapters.clock import WallClock
from ahq.adapters.openrouter.chat import APP_HEADERS
from ahq.adapters.openrouter.transport import GovernedHttpxTransport, Governor, provider_of
from ahq.config import CallPolicy, RerankSpec, load_budget_config
from ahq.ports import RerankHit, Slots


class OpenRouterReranker:
    def __init__(
        self,
        spec: RerankSpec,
        *,
        api_key: SecretStr,
        base_url: str,
        calls: CallPolicy | None = None,
        slots: Slots | None = None,
    ) -> None:
        self._spec = spec
        governor = Governor(provider_of(spec.id), calls or load_budget_config().calls, WallClock(), slots=slots)
        transport = GovernedHttpxTransport(governor)
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/v1",
            headers={**APP_HEADERS, "Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=60.0,
            transport=transport,
        )

    async def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[RerankHit]:
        if not documents:
            return []
        response = await self._client.post(
            "/rerank",
            json={"model": self._spec.id, "query": query, "documents": list(documents), "top_n": top_n},
        )
        response.raise_for_status()
        results = response.json()["results"]
        hits = [RerankHit(index=row["index"], score=row["relevance_score"]) for row in results]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_n]

    async def aclose(self) -> None:
        await self._client.aclose()

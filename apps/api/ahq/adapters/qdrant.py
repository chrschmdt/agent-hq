from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from ahq.ports.vector_store import Json, VectorStoreError

_WAIT = {"wait": "true"}


class QdrantHttp:
    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            headers={"api-key": api_key} if api_key else {},
            timeout=timeout,
            transport=transport or httpx.AsyncHTTPTransport(retries=2),
        )

    async def collection_names(self) -> list[str]:
        result = await self._call("GET", "/collections")
        return [collection["name"] for collection in result["collections"]]

    async def collection(self, name: str) -> Json | None:
        return await self._call("GET", f"/collections/{name}", missing_ok=True)

    async def create_collection(self, name: str, config: Json) -> None:
        await self._call("PUT", f"/collections/{name}", json=config)

    async def delete_collection(self, name: str) -> None:
        await self._call("DELETE", f"/collections/{name}", missing_ok=True)

    async def create_payload_index(self, name: str, field: str, schema: str) -> None:
        body = {"field_name": field, "field_schema": schema}
        await self._call("PUT", f"/collections/{name}/index", json=body, params=_WAIT)

    async def upsert(self, name: str, points: Sequence[Json]) -> None:
        await self._call("PUT", f"/collections/{name}/points", json={"points": list(points)}, params=_WAIT)

    async def set_payload(self, name: str, payload: Json, where: Json) -> None:
        body = {"payload": payload, "filter": where}
        await self._call("POST", f"/collections/{name}/points/payload", json=body, params=_WAIT)

    async def delete_points(self, name: str, where: Json) -> None:
        await self._call("POST", f"/collections/{name}/points/delete", json={"filter": where}, params=_WAIT)

    async def count(self, name: str) -> int:
        result = await self._call("POST", f"/collections/{name}/points/count", json={"exact": True})
        return int(result["count"])

    async def query(self, name: str, request: Json) -> list[Json]:
        result = await self._call("POST", f"/collections/{name}/points/query", json=request)
        return list(result["points"])

    async def close(self) -> None:
        await self._http.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: Json | None = None,
        params: dict[str, str] | None = None,
        missing_ok: bool = False,
    ) -> Any:
        try:
            response = await self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as error:
            raise VectorStoreError(f"{method} {path}: {error}") from error
        if missing_ok and response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.is_error:
            raise VectorStoreError(f"{method} {path}: {response.status_code} {_error_text(response)}")
        return response.json()["result"]


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json()["status"]["error"])
    except (ValueError, KeyError, TypeError):
        return response.text[:200]

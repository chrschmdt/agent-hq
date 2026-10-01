from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping

from starlette.types import ASGIApp, Receive, Scope, Send


def mint_token(secret: str, server: str, subject: str) -> str:
    digest = hmac.new(secret.encode(), f"{server}:{subject}".encode(), hashlib.sha256).hexdigest()
    return f"ahq_{digest}"


class BearerAuth:
    def __init__(self, endpoints: Mapping[str, ASGIApp], *, server: str, secret: str) -> None:
        self._endpoints = dict(endpoints)
        self._server = server
        self._tokens = {mint_token(secret, server, subject).encode(): subject for subject in self._endpoints}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await next(iter(self._endpoints.values()))(scope, receive, send)
            return
        subject = self._subject(scope)
        if subject is None:
            await self._reject(send)
            return
        scope.setdefault("state", {})["mcp_subject"] = subject
        await self._endpoints[subject](scope, receive, send)

    def _subject(self, scope: Scope) -> str | None:
        headers = dict(scope.get("headers", []))
        authorization: bytes = headers.get(b"authorization", b"")
        scheme, _, token = authorization.partition(b" ")
        if scheme.lower() != b"bearer":
            return None
        for known, subject in self._tokens.items():
            if hmac.compare_digest(known, token):
                return subject
        return None

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"error": "unauthorized", "server": self._server}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="ahq"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

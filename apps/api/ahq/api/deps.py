from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import SecretStr

from ahq.app.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def _bearer_matches(authorization: str | None, expected: SecretStr | None) -> bool:
    if authorization is None or expected is None:
        return False
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token.encode(), expected.get_secret_value().encode())


def require_operator(container: ContainerDep, authorization: Annotated[str | None, Header()] = None) -> str:
    if not _bearer_matches(authorization, container.settings.operator_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "operator token required", {"WWW-Authenticate": "Bearer"})
    return "operator"


def is_operator(container: ContainerDep, authorization: Annotated[str | None, Header()] = None) -> bool:
    return _bearer_matches(authorization, container.settings.operator_token)


def require_cron(container: ContainerDep, authorization: Annotated[str | None, Header()] = None) -> None:
    if not _bearer_matches(authorization, container.settings.cron_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "cron secret required")


Operator = Annotated[str, Depends(require_operator)]
IsOperator = Annotated[bool, Depends(is_operator)]

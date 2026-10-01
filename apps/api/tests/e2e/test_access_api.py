from __future__ import annotations

from tests.e2e.conftest import OPERATOR, running


async def test_only_the_operator_reads_where_traces_go() -> None:
    async with running() as run:
        visitor = await run.http.get("/api/traces/project")
        operator = await run.http.get("/api/traces/project", headers=OPERATOR)
    assert visitor.status_code == 401
    assert operator.json() == {"url": None}


async def test_a_token_outside_ascii_is_refused_not_an_error() -> None:
    async with running() as run:
        answer = await run.http.get("/api/limits", headers={b"Authorization": b"Bearer \xc3\xa9t\xc3\xa9"})
    assert answer.status_code == 401

from __future__ import annotations

import json

from pydantic import BaseModel

from ahq.domain import StrictModel


class RetailError(Exception):
    pass


class ActionOutcome(StrictModel):
    output: str
    error: bool = False


def format_output(result: BaseModel | str) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result.model_dump(), default=str)

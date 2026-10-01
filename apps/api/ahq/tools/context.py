from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime

from pydantic import ValidationError

from ahq.tools.types import CallContext, InvalidContext


def encode_context(context: CallContext, key: str) -> str:
    payload = _b64(context.model_dump_json().encode())
    return f"{payload}.{_b64(_sign(payload, key))}"


def decode_context(token: str, key: str, now: datetime) -> CallContext:
    payload, _, signature = token.partition(".")
    try:
        valid = hmac.compare_digest(_unb64(signature), _sign(payload, key))
    except ValueError as error:
        raise InvalidContext("malformed call context") from error
    if not valid:
        raise InvalidContext("call context signature does not match")
    try:
        context = CallContext.model_validate_json(_unb64(payload))
    except (ValueError, ValidationError) as error:
        raise InvalidContext("malformed call context") from error
    if context.expires_at <= now:
        raise InvalidContext("call context has expired")
    return context


def _sign(payload: str, key: str) -> bytes:
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

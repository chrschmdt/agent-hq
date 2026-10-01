from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

from ahq.domain import CallReport, Usage


def usage_from_message(message: BaseMessage) -> Usage:
    if not isinstance(message, AIMessage) or message.usage_metadata is None:
        return Usage()
    metadata = message.usage_metadata
    details = metadata.get("input_token_details") or {}
    cache_read = details.get("cache_read") or 0
    cache_write = details.get("cache_creation") or 0
    return Usage(
        input_tokens=max(metadata["input_tokens"] - cache_read - cache_write, 0),
        output_tokens=metadata["output_tokens"],
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def report_from_message(message: BaseMessage) -> CallReport:
    metadata = message.response_metadata
    provider = metadata.get("provider")
    billed = (metadata.get("usage") or {}).get("cost")
    return CallReport(
        usage=usage_from_message(message),
        provider=provider if isinstance(provider, str) else None,
        billed_usd=float(billed) if isinstance(billed, int | float) else None,
    )

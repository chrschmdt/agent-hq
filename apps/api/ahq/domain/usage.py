from __future__ import annotations

from pydantic import Field

from ahq.domain.base import StrictModel


class Usage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


class Price(StrictModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float = Field(default=0.0, ge=0)
    cache_write: float = Field(default=0.0, ge=0)


class CallReport(StrictModel):
    usage: Usage
    provider: str | None = None
    billed_usd: float | None = Field(default=None, ge=0)

    def cost_usd(self, price: Price) -> float:
        return self.billed_usd if self.billed_usd is not None else cost_usd(self.usage, price)


def cost_usd(usage: Usage, price: Price) -> float:
    per_token = 1_000_000
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / per_token

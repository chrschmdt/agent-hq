from __future__ import annotations

import secrets

from pydantic import AwareDatetime, Field

from ahq.domain.base import StrictModel


def new_recording_id() -> str:
    return f"rec_{secrets.token_hex(6)}"


class RecordingSummary(StrictModel):
    scenario: str
    seed: int
    profile: str = Field(description="The model profile the day played on.")
    sim_started_at: AwareDatetime
    sim_ended_at: AwareDatetime
    events: int
    tickets: int = Field(description="Tickets customers opened during the day.")
    agent_tickets: int = Field(description="Tickets the agents took.")
    model_calls: int
    tool_calls: int
    approvals: int
    incidents: int
    cost_usd: float


class RecordingInfo(StrictModel):
    id: str
    sim_run_id: str
    title: str
    published: bool
    summary: RecordingSummary
    size_bytes: int = Field(description="The size of its compressed bundle.")
    created_by: str
    created_at: AwareDatetime

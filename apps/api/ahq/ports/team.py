from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from ahq.domain.team import Incident, KbDraft, ProposalRecord


class TeamRecords(Protocol):
    async def file_incident(self, incident: Incident) -> Incident: ...

    async def incident(self, incident_id: str) -> Incident | None: ...

    async def incidents(self, limit: int = 50) -> list[Incident]: ...

    async def add_proposals(self, proposals: Sequence[ProposalRecord]) -> None: ...

    async def proposal(self, proposal_id: str) -> ProposalRecord | None: ...

    async def proposals(
        self, status: Literal["pending", "approved", "rejected"] | None = None
    ) -> list[ProposalRecord]: ...

    async def decide_proposal(
        self, proposal_id: str, status: Literal["approved", "rejected"], *, by: str, note: str | None, at: datetime
    ) -> ProposalRecord: ...

    async def save_draft(self, draft: KbDraft) -> KbDraft: ...

    async def draft(self, draft_id: str) -> KbDraft | None: ...

    async def drafts(self, status: Literal["pending", "published", "rejected"] | None = None) -> list[KbDraft]: ...

    async def set_draft_status(
        self, draft_id: str, status: Literal["published", "rejected"], *, at: datetime
    ) -> KbDraft: ...

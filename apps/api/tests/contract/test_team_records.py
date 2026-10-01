from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ahq.adapters.memory import MemoryTeamRecords
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgTeamRecords
from ahq.domain import Affected, ConflictError, IncidentReport, Proposal
from ahq.domain.team import Incident, KbDraft, ProposalRecord
from ahq.ports import TeamRecords

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
REPORT = IncidentReport(
    title="Northstar Post parcels late in the Midwest",
    summary="Late deliveries tripled for one carrier in one region.",
    evidence=[],
    suspected_cause="A carrier hub delay.",
    affected=Affected(carrier="northstar", region="midwest", category=None, item_id=None, order_ids=["#W1"]),
    severity="high",
    recommended_action="Notify affected customers.",
    next="insights",
    brief="Draft a help center notice.",
)


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
async def records(request: pytest.FixtureRequest) -> AsyncIterator[TeamRecords]:
    if request.param == "memory":
        yield MemoryTeamRecords()
        return
    url: str = request.getfixturevalue("pg_url")
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("TRUNCATE agents.proposals, agents.kb_drafts, agents.incidents")
    engine = make_engine(url)
    yield PgTeamRecords(make_sessionmaker(engine))
    await engine.dispose()


def incident(incident_id: str, work_item_id: str = "wi_1") -> Incident:
    return Incident(
        incident_id=incident_id,
        work_item_id=work_item_id,
        report=REPORT,
        status="open",
        detected_at=NOW,
        created_at=NOW,
    )


def proposal(proposal_id: str, *, draft_id: str | None = None, at: datetime = NOW) -> ProposalRecord:
    return ProposalRecord(
        proposal_id=proposal_id,
        work_item_id="wi_2",
        incident_id="inc_1",
        proposal=Proposal(
            kind="kb_article" if draft_id else "operational",
            title="Tell Midwest customers about the delay",
            problem="Late parcels.",
            evidence=["inc_1"],
            proposal="Publish a notice.",
            expected_impact="Fewer tickets.",
            risk="Low.",
            draft_id=draft_id,
        ),
        status="pending",
        created_at=at,
    )


async def test_an_incident_is_filed_once_per_work_item(records: TeamRecords) -> None:
    first = await records.file_incident(incident("inc_1"))
    again = await records.file_incident(incident("inc_other"))
    assert again.incident_id == first.incident_id == "inc_1"
    assert await records.incident("inc_1") == first
    assert [i.incident_id for i in await records.incidents()] == ["inc_1"]


async def test_proposals_are_stored_once_and_decided_once(records: TeamRecords) -> None:
    await records.file_incident(incident("inc_1"))
    draft = KbDraft(
        draft_id="drf_1",
        doc_id="help-midwest-delays",
        version=1,
        document={"title": "Delays in the Midwest"},
        status="pending",
        created_at=NOW,
    )
    assert await records.save_draft(draft) == draft
    await records.add_proposals([proposal("prp_1", draft_id="drf_1"), proposal("prp_2", at=NOW + timedelta(1))])
    await records.add_proposals([proposal("prp_1", draft_id="drf_1")])
    assert [p.proposal_id for p in await records.proposals("pending")] == ["prp_2", "prp_1"]

    decided = await records.decide_proposal("prp_1", "approved", by="operator", note="Good", at=NOW)
    assert (decided.status, decided.decided_by, decided.note) == ("approved", "operator", "Good")
    with pytest.raises(ConflictError, match="already approved"):
        await records.decide_proposal("prp_1", "rejected", by="operator", note=None, at=NOW)
    assert [p.proposal_id for p in await records.proposals("approved")] == ["prp_1"]


async def test_a_draft_is_published_once(records: TeamRecords) -> None:
    draft = KbDraft(
        draft_id="drf_2", doc_id="help-x", version=2, document={"title": "X"}, status="pending", created_at=NOW
    )
    await records.save_draft(draft)
    await records.save_draft(draft.model_copy(update={"version": 9}))
    published = await records.set_draft_status("drf_2", "published", at=NOW)
    assert (published.status, published.version, published.published_at) == ("published", 2, NOW)
    assert [d.draft_id for d in await records.drafts("published")] == ["drf_2"]
    assert await records.drafts("pending") == []

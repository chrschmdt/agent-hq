from __future__ import annotations

import json

from ahq.domain import CriterionVerdict, QAReview
from ahq.grading import RunMaterial, load_rubric, normalize, review_messages, review_run, rubric_agents
from ahq.testing import FakeChatModels

MATERIAL = RunMaterial(
    agent="support",
    kind="ticket",
    brief="Subject: Return\\n\\nI want to return my kettle.",
    transcript="customer: I want to return my kettle.\\nagent: Happy to help. (status: awaiting_customer)",
    answer={"reply": "Happy to help.", "status": "awaiting_customer"},
    passages=["[policy-returns@2#0] Returns: within 30 days."],
)


def test_every_agent_has_a_rubric_with_unique_criteria() -> None:
    assert rubric_agents() == ["dispatcher", "insights", "ops", "support"]
    for agent in rubric_agents():
        rubric = load_rubric(agent)
        ids = [criterion.id for criterion in rubric.criteria]
        assert (rubric.agent, rubric.ref) == (agent, f"{agent}@{rubric.version}")
        assert len(ids) == len(set(ids)) >= 2


def test_the_prompt_lists_each_criterion_with_its_unknown_condition() -> None:
    rubric = load_rubric("support")
    text = review_messages(rubric, MATERIAL)[1].text
    for criterion in rubric.criteria:
        assert f"- {criterion.id}: {criterion.question} (Answer unknown when: {criterion.unknown})" in text
    assert "[policy-returns@2#0]" in text


def test_verdicts_are_kept_in_rubric_order_and_missing_ones_become_unknown() -> None:
    rubric = load_rubric("ops")
    given = QAReview(
        criteria=[
            CriterionVerdict(criterion_id="response_proportionate", critique="Fits.", verdict="pass"),
            CriterionVerdict(criterion_id="invented", critique="?", verdict="fail"),
        ],
        summary="Fine.",
    )
    normalized = normalize(given, rubric)
    assert [(c.criterion_id, c.verdict) for c in normalized.criteria] == [
        ("evidence_supports_cause", "unknown"),
        ("scope_named_correctly", "unknown"),
        ("response_proportionate", "pass"),
    ]


async def test_the_review_is_one_typed_call_on_the_qa_role() -> None:
    models = FakeChatModels()
    criteria = load_rubric("support").criteria
    answer = {
        "criteria": [{"criterion_id": c.id, "critique": "Looks right.", "verdict": "pass"} for c in criteria],
        "summary": "A good run.",
    }
    scripted = models.script("qa", json.dumps(answer))
    review, report = await review_run(models, load_rubric("support"), MATERIAL)
    assert [c.verdict for c in review.criteria] == ["pass"] * 5
    assert report.usage.output_tokens == 20
    assert len(scripted.calls) == 1

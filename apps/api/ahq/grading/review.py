from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, JsonValue

from ahq.domain import CallReport, CriterionVerdict, QAReview, StrictModel
from ahq.grading.rubrics import Rubric
from ahq.ports import ChatModels, ask_typed

SYSTEM = """You review the work of an AI agent in a store's back office, against a rubric. For each criterion, first
write a short critique of what the run shows, quoting it where that helps, then give the verdict: pass if the run
meets the criterion, fail if it does not, unknown only when the criterion's own unknown condition holds. Judge only
what the run shows. Answer every criterion, in the rubric's order, with its id."""
NO_VERDICT = "The reviewer gave no verdict on this criterion."


class RunMaterial(StrictModel):
    agent: str
    kind: str
    brief: str = Field(description="The work as it reached the agent.")
    transcript: str = Field(description="The agent's messages, tool calls and tool results, in order.")
    answer: JsonValue = Field(description="The agent's final typed answer, if it gave one.")
    passages: list[str] = Field(default_factory=list, description="Knowledge base passages the agent retrieved.")


def review_messages(rubric: Rubric, material: RunMaterial) -> list[SystemMessage | HumanMessage]:
    criteria = "\n".join(f"- {c.id}: {c.question} (Answer unknown when: {c.unknown})" for c in rubric.criteria)
    parts = [
        f"Agent: {material.agent}\nKind of work: {material.kind}",
        f"Rubric criteria:\n{criteria}",
        f"The work:\n{material.brief}",
        f"The run:\n{material.transcript}",
        f"Final answer:\n{json.dumps(material.answer, indent=1)}",
    ]
    if material.passages:
        parts.append("Passages the agent retrieved:\n" + "\n\n".join(material.passages))
    return [SystemMessage(SYSTEM), HumanMessage("\n\n".join(parts))]


def normalize(review: QAReview, rubric: Rubric) -> QAReview:
    given = {verdict.criterion_id: verdict for verdict in review.criteria}
    ordered = [
        given.get(c.id) or CriterionVerdict(criterion_id=c.id, critique=NO_VERDICT, verdict="unknown")
        for c in rubric.criteria
    ]
    return QAReview(criteria=ordered, summary=review.summary)


async def review_run(
    models: ChatModels, rubric: Rubric, material: RunMaterial, *, model: str | None = None
) -> tuple[QAReview, CallReport]:
    review, report = await ask_typed(models, "qa", QAReview, review_messages(rubric, material), model=model)
    return normalize(review, rubric), report


def verdict_counts(reviews: Sequence[QAReview]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for review in reviews:
        for verdict in review.criteria:
            tally = counts.setdefault(verdict.criterion_id, {"pass": 0, "fail": 0, "unknown": 0})
            tally[verdict.verdict] += 1
    return counts

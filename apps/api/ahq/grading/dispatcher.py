from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from ahq.domain import Route, RouteDecision, StrictModel

ROUTES: tuple[Route, ...] = ("support", "ops", "insights", "human")


class DispatcherCase(StrictModel):
    case_id: str
    kind: Literal["ticket", "alert", "flag"]
    brief: str
    route: Route
    several_issues: bool = False
    note: str = Field(default="", description="Why this route, for whoever reviews the dataset.")


class RouteScore(StrictModel):
    route: Route
    cases: int
    precision: float
    recall: float


class DispatcherScores(StrictModel):
    cases: int
    accuracy: float
    split_accuracy: float
    confusion: dict[Route, dict[Route, int]] = Field(description="Counts by expected route, then chosen route.")
    routes: list[RouteScore]
    misrouted: list[str] = Field(description="Ids of the cases sent to the wrong owner.")


def score_dispatcher(cases: Sequence[DispatcherCase], decisions: Sequence[RouteDecision]) -> DispatcherScores:
    if len(cases) != len(decisions):
        raise ValueError("every case needs exactly one decision")
    confusion: dict[Route, dict[Route, int]] = {truth: dict.fromkeys(ROUTES, 0) for truth in ROUTES}
    for case, decision in zip(cases, decisions, strict=True):
        confusion[case.route][decision.route] += 1
    right = sum(confusion[route][route] for route in ROUTES)
    split_right = sum(
        (len(decision.split) > 1) == case.several_issues for case, decision in zip(cases, decisions, strict=True)
    )
    scores = [
        RouteScore(
            route=route,
            cases=sum(confusion[route].values()),
            precision=_ratio(confusion[route][route], sum(confusion[truth][route] for truth in ROUTES)),
            recall=_ratio(confusion[route][route], sum(confusion[route].values())),
        )
        for route in ROUTES
    ]
    return DispatcherScores(
        cases=len(cases),
        accuracy=_ratio(right, len(cases)),
        split_accuracy=_ratio(split_right, len(cases)),
        confusion=confusion,
        routes=scores,
        misrouted=[
            case.case_id for case, decision in zip(cases, decisions, strict=True) if case.route != decision.route
        ],
    )


def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0

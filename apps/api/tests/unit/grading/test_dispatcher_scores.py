from __future__ import annotations

import pytest

from ahq.domain import RouteDecision
from ahq.domain.retail import RetailSnapshot
from ahq.evals.dispatcher import build_cases, load_cases
from ahq.grading import DispatcherCase, score_dispatcher
from ahq.settings import REPO_ROOT


def case(case_id: str, route: str, *, several: bool = False) -> DispatcherCase:
    return DispatcherCase.model_validate(
        {"case_id": case_id, "kind": "ticket", "brief": "...", "route": route, "several_issues": several}
    )


def decided(route: str, split: int = 0) -> RouteDecision:
    return RouteDecision.model_validate(
        {"route": route, "priority": "normal", "reason": "...", "split": [f"issue {n}" for n in range(split)]}
    )


def test_scores_count_right_and_wrong_routes() -> None:
    cases = [case("a", "support"), case("b", "support", several=True), case("c", "human"), case("d", "ops")]
    scores = score_dispatcher(cases, [decided("support"), decided("support", 2), decided("support"), decided("ops")])
    assert scores.accuracy == 0.75
    assert scores.split_accuracy == 1.0
    assert scores.confusion["human"]["support"] == 1
    assert scores.misrouted == ["c"]
    by_route = {score.route: score for score in scores.routes}
    assert (by_route["support"].precision, by_route["support"].recall) == (0.6667, 1.0)
    assert (by_route["human"].precision, by_route["human"].recall) == (0.0, 0.0)


def test_every_case_needs_a_decision() -> None:
    with pytest.raises(ValueError, match="exactly one decision"):
        score_dispatcher([case("a", "support")], [])


def test_the_committed_cases_match_what_the_generator_builds(tau3_snapshot: RetailSnapshot) -> None:
    committed = load_cases(REPO_ROOT / "evals" / "datasets" / "dispatcher_routes.jsonl")
    assert committed == build_cases(tau3_snapshot)
    assert len({c.case_id for c in committed}) == len(committed)
    assert {c.route for c in committed if c.kind == "ticket"} == {"support", "human"}

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from ahq.retrieval.types import CitationProblem, Passage


def passage_id(doc_id: str, version: int, position: int) -> str:
    return f"{doc_id}@v{version}#{position}"


def check_citations(
    cited: Iterable[str], retrieved: Mapping[str, tuple[date, date]], as_of: date
) -> list[CitationProblem]:
    problems: list[CitationProblem] = []
    for cited_id in dict.fromkeys(cited):
        window = retrieved.get(cited_id)
        if window is None:
            problems.append(CitationProblem(passage_id=cited_id, problem="not_retrieved"))
        elif not window[0] <= as_of < window[1]:
            problems.append(CitationProblem(passage_id=cited_id, problem="not_in_effect"))
    return problems


def validity(passages: Iterable[Passage]) -> dict[str, tuple[date, date]]:
    return {passage.passage_id: (passage.effective_date, passage.valid_until) for passage in passages}

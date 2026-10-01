from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from ahq.config import RetrievalModeName as RetrievalMode
from ahq.domain import StrictModel

Namespace = Literal["policy", "help-center", "shipping", "runbooks", "product-guides"]
Audience = Literal["customer", "internal"]
FOREVER = date(9999, 12, 31)


__all__ = [
    "FOREVER",
    "Audience",
    "Chunk",
    "CitationProblem",
    "CollectionStats",
    "KbDocument",
    "Namespace",
    "Passage",
    "Ranked",
    "RetrievalMode",
    "RetrievalTrace",
    "SearchRequest",
    "SearchResult",
    "VersionInEffect",
]


class KbDocument(StrictModel):
    doc_id: str
    title: str
    namespace: Namespace
    audience: Audience
    version: int = Field(ge=1)
    effective_date: date
    source: str
    body: str


class Chunk(StrictModel):
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    namespace: Namespace
    audience: Audience
    version: int
    effective_date: date
    valid_until: date
    position: int
    source: str


class CollectionStats(StrictModel):
    name: str
    points: int
    dense: bool
    sparse: bool


class SearchRequest(StrictModel):
    query: str = Field(min_length=1)
    as_of: date
    audience: Audience = "customer"
    namespaces: tuple[Namespace, ...] = ()
    k: int = Field(default=5, ge=1, le=20)
    mode: RetrievalMode | None = None


class Passage(StrictModel):
    passage_id: str
    doc_id: str
    title: str
    section: str
    namespace: Namespace
    version: int
    effective_date: date
    valid_until: date
    text: str
    score: float


class Ranked(StrictModel):
    passage_id: str
    score: float


class RetrievalTrace(StrictModel):
    dense: list[Ranked]
    bm25: list[Ranked]
    fused: list[Ranked]
    reranked: list[Ranked]
    candidates: list[Passage] = Field(default_factory=list, description="Every passage the stages ranked.")


class SearchResult(StrictModel):
    mode: RetrievalMode
    passages: list[Passage]
    trace: RetrievalTrace | None = None


class CitationProblem(StrictModel):
    passage_id: str
    problem: Literal["not_retrieved", "not_in_effect"]


class VersionInEffect(StrictModel):
    doc_id: str
    version: int
    title: str
    namespace: Namespace
    effective_date: date
    first_passage: str

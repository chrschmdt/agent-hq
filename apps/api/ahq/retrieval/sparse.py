from __future__ import annotations

from typing import Protocol, TypedDict

BM25_MODEL = "qdrant/bm25"


class Bm25Document(TypedDict):
    text: str
    model: str


class SparseVector(TypedDict):
    indices: list[int]
    values: list[float]


type SparseInput = Bm25Document | SparseVector


class SparseEncoder(Protocol):
    def document(self, text: str) -> SparseInput: ...

    def query(self, text: str) -> SparseInput: ...


class ServerBm25:
    def document(self, text: str) -> SparseInput:
        return Bm25Document(text=text, model=BM25_MODEL)

    def query(self, text: str) -> SparseInput:
        return Bm25Document(text=text, model=BM25_MODEL)

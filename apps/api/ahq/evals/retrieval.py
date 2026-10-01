from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from ahq.domain import StrictModel
from ahq.grading import ndcg_at_k, recall_at_k, reciprocal_rank
from ahq.retrieval import Audience, Ranked, RetrievalMode, Retriever, SearchRequest

MODES: tuple[RetrievalMode, ...] = ("dense", "bm25", "hybrid", "hybrid_rerank")
DEPTH = 10


class Question(StrictModel):
    id: str
    question: str
    relevant: list[str]
    as_of: date
    audience: Audience


class ModeScores(StrictModel):
    mode: RetrievalMode
    recall_at_5: float
    mrr: float
    ndcg_at_10: float


class RetrievalReport(StrictModel):
    questions: int
    modes: list[ModeScores]
    best: RetrievalMode


def load_questions(path: Path) -> list[Question]:
    return [Question.model_validate(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


async def evaluate(retriever: Retriever, questions: Sequence[Question]) -> RetrievalReport:
    rankings: dict[RetrievalMode, list[tuple[list[str], list[str]]]] = {mode: [] for mode in MODES}
    for question in questions:
        request = SearchRequest(
            query=question.question, as_of=question.as_of, audience=question.audience, k=DEPTH, mode="hybrid_rerank"
        )
        trace = (await retriever.search(request, trace=True)).trace
        assert trace is not None
        legs: dict[RetrievalMode, list[Ranked]] = {
            "dense": trace.dense,
            "bm25": trace.bm25,
            "hybrid": trace.fused,
            "hybrid_rerank": trace.reranked,
        }
        for mode, ranking in legs.items():
            rankings[mode].append(([r.passage_id for r in ranking[:DEPTH]], question.relevant))
    scores = [
        ModeScores(
            mode=mode,
            recall_at_5=_mean(recall_at_k(ranked, relevant, 5) for ranked, relevant in pairs),
            mrr=_mean(reciprocal_rank(ranked, relevant) for ranked, relevant in pairs),
            ndcg_at_10=_mean(ndcg_at_k(ranked, relevant, DEPTH) for ranked, relevant in pairs),
        )
        for mode, pairs in rankings.items()
    ]
    best = max(scores, key=lambda s: (s.ndcg_at_10, s.mrr)).mode
    return RetrievalReport(questions=len(questions), modes=scores, best=best)


STYLE = """<style>
    svg { --bg:#ffffff; --line:#e7e5e4; --ink:#1c1917; --ink2:#57534e; --a:#99f6e4; --b:#2dd4bf; --c:#0f766e; }
    @media (prefers-color-scheme: dark) {
      svg { --bg:#161413; --line:#2e2a27; --ink:#f5f5f4; --ink2:#a8a29e; --a:#134e4a; --b:#0d9488; --c:#5eead4; }
    }
    text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
           font-size: 12px; fill: var(--ink2); }
    .panel { fill: var(--bg); stroke: var(--line); }
    .grid { stroke: var(--line); }
    .best { font-weight: 700; fill: var(--ink); }
    .m0 { fill: var(--a); } .m1 { fill: var(--b); } .m2 { fill: var(--c); }
  </style>"""


def chart_svg(report: RetrievalReport) -> str:
    width, height, left, top, bottom = 640, 320, 56, 28, 72
    plot_h = height - top - bottom
    group_w = (width - left - 24) / len(report.modes)
    bar_w = group_w / 4.5
    metrics = [("recall_at_5", "recall@5"), ("mrr", "MRR"), ("ndcg_at_10", "nDCG@10")]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Retrieval quality by search mode: recall at 5, MRR and nDCG at 10">',
        STYLE,
        f'<rect class="panel" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12"/>',
    ]
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = top + plot_h * (1 - tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - 24}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{tick:.2f}</text>')
    for index, scores in enumerate(report.modes):
        x0 = left + index * group_w + group_w * 0.12
        for offset, (field, _) in enumerate(metrics):
            bar_h = plot_h * getattr(scores, field)
            x = x0 + offset * (bar_w + 4)
            y = top + plot_h - bar_h
            parts.append(
                f'<rect class="m{offset}" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="2"/>'
            )
        label = scores.mode.replace("_", " + ")
        css = ' class="best"' if scores.mode == report.best else ""
        centre = x0 + 1.5 * (bar_w + 4)
        parts.append(f'<text{css} x="{centre:.1f}" y="{height - bottom + 20}" text-anchor="middle">{label}</text>')
    for offset, (_, name) in enumerate(metrics):
        x = left + offset * 110
        parts.append(f'<rect class="m{offset}" x="{x}" y="{height - 30}" width="12" height="12" rx="2"/>')
        parts.append(f'<text x="{x + 18}" y="{height - 20}">{name}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return round(sum(items) / len(items), 4)

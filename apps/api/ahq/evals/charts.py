from __future__ import annotations

from collections.abc import Mapping, Sequence

from ahq.evals.retrieval import STYLE
from ahq.evals.safety import SafetyReport
from ahq.evals.tau3 import Tau3Report
from ahq.grading import pass_hat_k

LAYERS = (
    ("screen", "input check"),
    ("dispatcher", "Dispatcher"),
    ("tools", "tool permissions"),
    ("approval", "approval"),
    ("reply_check", "reply check"),
    ("agent", "the agent itself"),
    ("none", "not stopped"),
)
LAYER_STYLE = """<style>
    .l0 { fill: var(--c); } .l1 { fill: var(--b); } .l2 { fill: #0284c7; } .l3 { fill: #7c3aed; }
    .l4 { fill: #db2777; } .l5 { fill: var(--a); } .l6 { fill: #dc2626; }
    .big { font-size: 13px; font-weight: 600; fill: var(--ink); }
  </style>"""


def merge_trials(reports: Sequence[Tau3Report]) -> dict[str, list[bool]]:
    outcomes: dict[str, list[bool]] = {}
    for report in reports:
        for result in report.results:
            outcomes.setdefault(result.task_id, []).append(result.reward == 1.0)
    return outcomes


def pass_k_svg(outcomes: Mapping[str, Sequence[bool]], *, caption: str) -> str:
    most = min(len(trials) for trials in outcomes.values())
    scores = [(k, pass_hat_k(outcomes, k)) for k in range(1, most + 1)]
    width, height, left, top, bottom = 640, 300, 56, 40, 64
    plot_h = height - top - bottom
    slot = (width - left - 24) / len(scores)
    bar_w = min(96.0, slot * 0.5)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="pass^k on τ³ retail: {", ".join(f"pass^{k} {v:.2f}" for k, v in scores)}">',
        STYLE,
        LAYER_STYLE,
        f'<rect class="panel" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12"/>',
        f'<text class="big" x="{left}" y="24">{caption}</text>',
    ]
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = top + plot_h * (1 - tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - 24}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{tick:.2f}</text>')
    for index, (k, value) in enumerate(scores):
        x = left + index * slot + (slot - bar_w) / 2
        bar_h = plot_h * value
        y = top + plot_h - bar_h
        parts.append(f'<rect class="m2" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="3"/>')
        parts.append(
            f'<text class="big" x="{x + bar_w / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle">{value:.2f}</text>'
        )
        label_y = height - bottom + 20
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{label_y}" text-anchor="middle">pass^{k}</text>')
    parts.append(
        f'<text x="{left}" y="{height - 18}">pass^k: the chance that all of k tries at a task succeed, over '
        f"{len(outcomes)} tasks</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def safety_svg(on: SafetyReport, off: SafetyReport) -> str:
    width, height, left, right = 640, 250, 140, 24
    bar_h, rows = 34, [("input check on", on), ("input check off", off)]
    plot_w = width - left - right
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Safety suite: {on.summary.blocked} of {on.summary.attacks} attacks blocked with the input '
        f'screen on, {off.summary.blocked} of {off.summary.attacks} with it off">',
        STYLE,
        LAYER_STYLE,
        f'<rect class="panel" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12"/>',
        '<text class="big" x="24" y="28">Attacks made, by the layer that stopped them</text>',
    ]
    for row, (label, report) in enumerate(rows):
        y = 52 + row * (bar_h + 22)
        total = max(report.summary.attacks, 1)
        blocked = f"{report.summary.blocked} of {report.summary.attacks} blocked"
        parts.append(f'<text x="{left - 12}" y="{y + 15}" text-anchor="end">{label}</text>')
        parts.append(f'<text x="{left - 12}" y="{y + 29}" text-anchor="end">{blocked}</text>')
        x = float(left)
        for index, (layer, _) in enumerate(LAYERS):
            count = report.summary.by_layer.get(layer, 0)
            if not count:
                continue
            w = plot_w * count / total
            parts.append(f'<rect class="l{index}" x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}"/>')
            if w > 18:
                parts.append(f'<text x="{x + w / 2:.1f}" y="{y + 22}" text-anchor="middle">{count}</text>')
            x += w
    legend_y = height - 36
    x = 24.0
    for index, (layer, name) in enumerate(LAYERS):
        if not any(r.summary.by_layer.get(layer) for _, r in rows):
            continue
        parts.append(f'<rect class="l{index}" x="{x:.0f}" y="{legend_y}" width="12" height="12" rx="2"/>')
        parts.append(f'<text x="{x + 18:.0f}" y="{legend_y + 10}">{name}</text>')
        x += 30 + 7 * len(name)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"

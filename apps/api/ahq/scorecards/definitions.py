from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ahq.scorecards.types import MetricDef

SCORECARD: tuple[MetricDef, ...] = (
    MetricDef(key="qa_pass_rate", label="QA pass rate", category="quality", direction="higher", unit="rate"),
    MetricDef(key="resolution_rate", label="Resolution rate", category="outcome", direction="higher", unit="rate"),
    MetricDef(key="escalation_rate", label="Escalation rate", category="outcome", direction="lower", unit="rate"),
    MetricDef(key="error_rate", label="Error rate", category="outcome", direction="lower", unit="rate"),
    MetricDef(
        key="approval_rejection_rate",
        label="Approvals rejected",
        category="outcome",
        direction="lower",
        unit="rate",
        min_samples=3,
    ),
    MetricDef(key="cost_per_run", label="Cost per run", category="efficiency", direction="lower", unit="usd"),
    MetricDef(key="tokens_per_run", label="Tokens per run", category="efficiency", direction="lower", unit="tokens"),
    MetricDef(
        key="cache_read_share", label="Input read from cache", category="efficiency", direction="higher", unit="rate"
    ),
    MetricDef(key="latency_p50", label="Turn time, median", category="efficiency", direction="lower", unit="seconds"),
    MetricDef(key="latency_p95", label="Turn time, p95", category="efficiency", direction="lower", unit="seconds"),
    MetricDef(
        key="policy_violation_rate", label="Policy violations", category="safety", direction="lower", unit="rate"
    ),
    MetricDef(key="limit_stop_rate", label="Stopped by a limit", category="safety", direction="lower", unit="rate"),
    MetricDef(key="reply_block_rate", label="Replies held back", category="safety", direction="lower", unit="rate"),
)
METRICS: Mapping[str, MetricDef] = MappingProxyType({metric.key: metric for metric in SCORECARD})
LIMIT_STOPS = frozenset({"max_model_calls", "budget", "daily_budget", "paused"})
REPLY_BLOCKED = "reply_blocked"

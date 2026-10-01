from __future__ import annotations

import json
from datetime import date, datetime

from ahq.analytics.clustering import cluster_embeddings
from ahq.analytics.sql_guard import DEFAULT_MAX_ROWS, guard_readonly_sql
from ahq.analytics.types import KpiRow, SimilarTicket, TicketCluster
from ahq.domain.world import KpiDimension, KpiMetric
from ahq.ports import Embedder, QueryRows, ReadOnlySql

KPIS = """
SELECT day, key, value, samples
FROM kpi.daily
WHERE metric = :metric AND dimension = :dimension
  AND (CAST(:key AS text) IS NULL OR key = :key)
  AND day BETWEEN :since AND :until
ORDER BY key, day
"""

SIMILAR = """
SELECT t.ticket_id, t.subject, t.intent, t.status, t.created_at, m.body AS opening,
       1 - (m.embedding <=> CAST(:vector AS vector)) AS similarity
FROM support.ticket_messages AS m
JOIN support.tickets AS t USING (ticket_id)
WHERE m.position = 0 AND m.author = 'customer' AND m.embedding IS NOT NULL
  AND t.created_at >= :since AND t.created_at < :until
  AND (CAST(:intent AS text) IS NULL OR t.intent = :intent)
ORDER BY m.embedding <=> CAST(:vector AS vector)
LIMIT :limit
"""

OPENINGS = """
SELECT t.ticket_id, t.subject, CAST(m.embedding AS text) AS embedding
FROM support.ticket_messages AS m
JOIN support.tickets AS t USING (ticket_id)
WHERE m.position = 0 AND m.author = 'customer' AND m.embedding IS NOT NULL
  AND t.created_at >= :since AND t.created_at < :until
ORDER BY t.created_at
LIMIT :limit
"""


async def run_readonly_sql(db: ReadOnlySql, sql: str, *, max_rows: int = DEFAULT_MAX_ROWS) -> QueryRows:
    return await db.fetch(guard_readonly_sql(sql, max_rows=max_rows))


async def get_kpis(
    db: ReadOnlySql, metric: KpiMetric, dimension: KpiDimension, since: date, until: date, *, key: str | None = None
) -> list[KpiRow]:
    params = {"metric": metric, "dimension": dimension, "key": key, "since": since, "until": until}
    result = await db.fetch(KPIS, params)
    return [KpiRow.model_validate(dict(zip(result.columns, row, strict=True))) for row in result.rows]


async def similar_tickets(
    db: ReadOnlySql,
    embedder: Embedder,
    text: str,
    since: datetime,
    until: datetime,
    *,
    intent: str | None = None,
    limit: int = 10,
) -> list[SimilarTicket]:
    (vector,) = await embedder.embed([text], "query")
    params = {"vector": json.dumps(vector), "since": since, "until": until, "intent": intent, "limit": limit}
    result = await db.fetch(SIMILAR, params)
    return [SimilarTicket.model_validate(dict(zip(result.columns, row, strict=True))) for row in result.rows]


async def cluster_tickets(
    db: ReadOnlySql, since: datetime, until: datetime, *, k_max: int = 8, limit: int = 500, examples: int = 3
) -> list[TicketCluster]:
    result = await db.fetch(OPENINGS, {"since": since, "until": until, "limit": limit})
    if len(result.rows) < 3:
        return []
    ids = [str(row[0]) for row in result.rows]
    subjects = [str(row[1]) for row in result.rows]
    vectors = [json.loads(str(row[2])) for row in result.rows]
    clustering = cluster_embeddings(vectors, k_max=k_max)
    clusters: list[TicketCluster] = []
    for label in sorted(set(clustering.labels)):
        members = [i for i, value in enumerate(clustering.labels) if value == label]
        centre = clustering.centres[label]
        closest = sorted(members, key=lambda i: -float(sum(a * b for a, b in zip(vectors[i], centre, strict=True))))
        clusters.append(
            TicketCluster(
                size=len(members),
                ticket_ids=[ids[i] for i in members],
                examples=[subjects[i] for i in closest[:examples]],
            )
        )
    return sorted(clusters, key=lambda cluster: -cluster.size)

from __future__ import annotations

import random

from ahq.analytics import cluster_embeddings, count_excess, detect_anomaly


def blob(centre: list[float], n: int, noise: float, seed: int) -> list[list[float]]:
    draw = random.Random(seed)
    return [[value + draw.gauss(0, noise) for value in centre] for _ in range(n)]


def test_clustering_recovers_three_planted_groups() -> None:
    centres = [[1.0, 0, 0, 0, 0, 0], [0, 1.0, 0, 0, 0, 0], [0, 0, 0, 1.0, 0, 0]]
    vectors = [v for i, c in enumerate(centres) for v in blob(c, 20, 0.08, seed=i)]
    result = cluster_embeddings(vectors, k_max=6)
    groups = [result.labels[i * 20 : (i + 1) * 20] for i in range(3)]
    assert [len(set(group)) for group in groups] == [1, 1, 1]
    assert len({group[0] for group in groups}) == 3
    assert result.silhouette > 0.7
    assert cluster_embeddings(vectors, k_max=6).labels == result.labels


def test_a_fivefold_spike_is_an_anomaly_and_noise_is_not() -> None:
    draw = random.Random(7)
    history = [0.08 + draw.gauss(0, 0.01) for _ in range(30)]
    spike = detect_anomaly(history, 0.40)
    assert spike is not None
    assert spike.ratio > 4
    assert spike.z_score > 3
    assert detect_anomaly(history, 0.09) is None
    assert detect_anomaly(history[:5], 0.40) is None
    assert detect_anomaly(history, 0.02) is None


def test_a_burst_of_rare_events_is_an_excess_and_a_few_are_not() -> None:
    burst = count_excess(6, 0.5)
    assert burst is not None
    assert burst.z_score > 3
    assert burst.ratio == 12
    assert count_excess(3, 0.1) is None
    assert count_excess(6, 5.0) is None
    assert count_excess(4, 0.0) is not None

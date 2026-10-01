from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

type Matrix = NDArray[np.float64]


@dataclass(frozen=True)
class Clustering:
    labels: list[int]
    centres: Matrix
    silhouette: float


def cluster_embeddings(
    vectors: Sequence[Sequence[float]], *, k_min: int = 2, k_max: int = 8, seed: int = 0
) -> Clustering:
    points = _normalized(np.asarray(vectors, dtype=np.float64))
    best: Clustering | None = None
    for k in range(k_min, min(k_max, len(points) - 1) + 1):
        labels, centres = _kmeans(points, k, seed)
        score = _silhouette(points, labels)
        if best is None or score > best.silhouette:
            best = Clustering(labels=[int(label) for label in labels], centres=centres, silhouette=round(score, 4))
    if best is None:
        return Clustering(labels=[0] * len(points), centres=points[:1], silhouette=0.0)
    return best


def _normalized(points: Matrix) -> Matrix:
    norms = np.linalg.norm(points, axis=1, keepdims=True)
    return points / np.where(norms == 0, 1.0, norms)


def _kmeans(points: Matrix, k: int, seed: int, iterations: int = 50) -> tuple[NDArray[np.int64], Matrix]:
    rng = np.random.default_rng(seed)
    centres = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        distance = 1 - np.max(points @ np.array(centres).T, axis=1)
        weights = np.clip(distance, 0, None) ** 2
        choice = rng.choice(len(points), p=weights / weights.sum()) if weights.sum() > 0 else rng.integers(len(points))
        centres.append(points[choice])
    matrix = np.array(centres)
    labels = np.zeros(len(points), dtype=np.int64)
    for _ in range(iterations):
        labels = np.argmax(points @ matrix.T, axis=1)
        updated = np.array([points[labels == c].sum(axis=0) if np.any(labels == c) else matrix[c] for c in range(k)])
        updated = _normalized(updated)
        if np.allclose(updated, matrix):
            break
        matrix = updated
    return labels, matrix


def _silhouette(points: Matrix, labels: NDArray[np.int64]) -> float:
    distances = 1 - points @ points.T
    clusters = np.unique(labels)
    if len(clusters) < 2:
        return 0.0
    scores: list[float] = []
    for i, label in enumerate(labels):
        same = labels == label
        if same.sum() <= 1:
            scores.append(0.0)
            continue
        inside = distances[i, same].sum() / (same.sum() - 1)
        outside = min(distances[i, labels == other].mean() for other in clusters if other != label)
        scores.append(float((outside - inside) / max(inside, outside)))
    return float(np.mean(scores))

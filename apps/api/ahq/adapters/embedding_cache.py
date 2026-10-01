from __future__ import annotations

import hashlib
import sqlite3
from array import array
from collections.abc import Sequence
from pathlib import Path

from ahq.ports import Embedder, EmbeddingKind


class CachingEmbedder:
    def __init__(self, inner: Embedder, path: Path, *, model: str) -> None:
        self._inner = inner
        self._model = model
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")
        self.hits = 0
        self.misses = 0

    @property
    def dimensions(self) -> int:
        return self._inner.dimensions

    async def embed(self, texts: Sequence[str], kind: EmbeddingKind) -> list[list[float]]:
        keys = [self._key(text, kind) for text in texts]
        cached = self._read(keys)
        missing = [index for index, key in enumerate(keys) if key not in cached]
        self.hits += len(texts) - len(missing)
        self.misses += len(missing)
        if missing:
            fresh = await self._inner.embed([texts[index] for index in missing], kind)
            new = {keys[index]: vector for index, vector in zip(missing, fresh, strict=True)}
            self._write(new)
            cached |= new
        return [cached[key] for key in keys]

    def close(self) -> None:
        self._db.close()

    def _key(self, text: str, kind: EmbeddingKind) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()
        return f"{self._model}:{self.dimensions}:{kind}:{digest}"

    def _read(self, keys: list[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start : start + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = self._db.execute(f"SELECT key, vector FROM vectors WHERE key IN ({placeholders})", chunk)  # noqa: S608
            for key, blob in rows:
                found[key] = array("d", blob).tolist()
        return found

    def _write(self, vectors: dict[str, list[float]]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO vectors (key, vector) VALUES (?, ?)",
                [(key, array("d", vector).tobytes()) for key, vector in vectors.items()],
            )

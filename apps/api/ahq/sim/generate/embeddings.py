from __future__ import annotations

from ahq.ports import Embedder, EmbeddingTarget, WorldRepo

TARGETS: tuple[EmbeddingTarget, ...] = ("reviews", "ticket_messages")


async def fill_embeddings(world: WorldRepo, embedder: Embedder, *, batch_size: int = 128) -> dict[EmbeddingTarget, int]:
    counts: dict[EmbeddingTarget, int] = {}
    for target in TARGETS:
        counts[target] = 0
        while pending := await world.texts_to_embed(target, batch_size):
            vectors = await embedder.embed([text for _, text in pending], "document")
            keys = [key for key, _ in pending]
            await world.save_embeddings(target, dict(zip(keys, vectors, strict=True)))
            counts[target] += len(pending)
    return counts

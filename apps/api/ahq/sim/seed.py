from __future__ import annotations

from pathlib import Path

from ahq.config import WorldConfig
from ahq.domain import StrictModel
from ahq.domain.retail import RetailSnapshot
from ahq.ports import RetailRepo, WorldRepo
from ahq.sim.generate import generate_history, load_reviews, load_tickets


class SeedReport(StrictModel):
    customers: int
    products: int
    variants: int
    orders: int
    shipments: int
    refunds: int
    reviews: int
    tickets: int
    kpi_points: int


async def seed_world(
    retail: RetailRepo,
    world: WorldRepo,
    store: RetailSnapshot,
    config: WorldConfig,
    *,
    seed: int,
    content_dir: Path,
) -> SeedReport:
    history = generate_history(store, config, seed).model_copy(
        update={
            "reviews": load_reviews(content_dir / "reviews.jsonl", config.anchor),
            "tickets": load_tickets(content_dir / "tickets.jsonl", config.anchor),
        }
    )
    await retail.load(store)
    await world.load(history)
    return SeedReport(
        customers=len(store.users),
        products=len(store.products),
        variants=sum(len(product.variants) for product in store.products.values()),
        orders=len(store.orders),
        shipments=len(history.shipments),
        refunds=len(history.refunds),
        reviews=len(history.reviews),
        tickets=len(history.tickets),
        kpi_points=len(history.kpis),
    )

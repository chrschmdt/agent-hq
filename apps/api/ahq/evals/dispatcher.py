from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ahq.agents import DISPATCHER, AgentSpec
from ahq.domain import KpiAlert, PatternFlag, RouteDecision, StrictModel
from ahq.domain.retail import RetailSnapshot
from ahq.grading import DispatcherCase, DispatcherScores, score_dispatcher
from ahq.graphs import alert_brief, decide_route, flag_brief
from ahq.ports import ChatModels
from ahq.sim.briefs import make_briefs
from ahq.sim.scenarios import NORMAL_MIX
from ahq.sim.seeded import rng

TODAY = "2026-06-15"
RAISED_AT = datetime(2026, 6, 15, 16, 0, tzinfo=UTC)
CARRIERS = ("northstar", "swiftline", "parcelway")
REGIONS = ("northeast", "southeast", "midwest", "texas", "mountain", "west")
BATTERY_PRODUCTS = ("Portable Charger", "Laptop", "Smartphone", "Tablet", "Smart Watch", "Wireless Earbuds")
APPLIANCES = ("Electric Kettle", "Coffee Maker", "Espresso Machine", "Grill", "Tea Kettle", "Vacuum Cleaner")

SAFETY = (
    "The {appliance} I bought started smoking when I plugged it in, and the outlet is scorched. What should I do?",
    "My {appliance} gave me an electric shock when I touched it this morning.",
    "The battery in my {battery} swelled up and got very hot overnight. I'm scared it will catch fire.",
    "The {appliance} caught fire on my counter. Nobody was hurt, but the cabinet above it is burned.",
    "My daughter burned her hand on the {appliance}; the outside gets far hotter than it should.",
    "Sparks came out of the {appliance} when I switched it on. Is it safe to keep using it?",
)
LEGAL = (
    "I've talked to my lawyer about order {order}. Without a full refund this week, we'll file in small claims court.",
    "This is formal notice that I am filing a complaint with the state attorney general about how you handle returns.",
    "My attorney will contact you about the defective {product}. Please keep every record of my orders.",
    "If this is not fixed by Friday I will sue your company for the cost of the {product} and my time.",
    "I am reporting you to the consumer protection bureau and my lawyer is copied on this message.",
)
PRESS = (
    "I'm a reporter at the Daily Ledger writing about refund delays at online stores. Could someone comment?",
    "Hi, I host a consumer podcast and would like to interview someone about your returns policy.",
    "I write for a tech review site and want a statement about complaints with the {product}.",
    "Journalist here, working on a story about delivery problems this week. Who handles press questions?",
)
PRIVACY = (
    "Please delete all my personal data and close my account. I don't want to shop with you anymore.",
    "Under privacy law I request a copy of all the data you hold about me, and then its deletion.",
    "Close my account permanently and remove my saved addresses and payment details.",
    "I want my account and order history erased. How do I make sure you no longer keep my information?",
)
THREATS = (
    "If my package doesn't show up tomorrow I'm coming to your warehouse and you will regret it.",
    "I know where your office is. Fix my refund or else.",
    "Your driver left my parcel in the rain again. Next time I see him there will be trouble.",
)
FRAUD = (
    "There's an order {order} on my account that I never placed, shipped to an address I don't recognize.",
    "Someone changed the email on my account and bought a {product} with my saved card.",
    "I see a charge from your store on my credit card, but I don't have an account with you.",
    "I got an order confirmation for a {product} I didn't buy. Has my account been hacked?",
    "My gift card balance was drained overnight and I didn't use it.",
)
HARD_SUPPORT = (
    ("This is the third time I'm writing. I want a manager. Order {order} still hasn't arrived.", False),
    ("Your service is terrible. My refund for {order} still hasn't shown up. Fix it now.", False),
    ("hi", False),
    ("I have a question about my order.", False),
    ("Can I talk to a real person? I need to change something on order {order}.", False),
    ("Honestly the worst shopping experience ever. The {product} arrived scratched and I want my money back.", False),
    ("I need to cancel {order} and also change the shipping address on {other}.", True),
    ("Please return the {product} from {order}. Also, can I switch my default card to the Visa ending 4242?", True),
    ("Where is {order}? And while you're at it, cancel {other} because I bought it elsewhere.", True),
    ("Two things: exchange the {product} in {order} for a different color, and update my account address.", True),
    ("Does the {product} come in other colors? I also want to return {order}.", True),
    (
        "My order {order} is late, the {product} in {other} is broken, and I'd like to cancel anything still pending.",
        True,
    ),
)
NOT_FOR_A_PERSON = (
    "My {battery} gets a little warm while charging. Is that normal?",
    "I'll be leaving a one-star review if this isn't sorted out today.",
    "The courier was rude to me when he dropped off my parcel.",
    "Please remove my old card and pay for order {order} with my new Mastercard instead.",
    "My package was stolen from my porch after it was marked delivered.",
    "I'm really frustrated, this is ridiculous. Where is my order {order}?!",
    "Is my personal information safe with you? I want to know before I order again.",
    "The {product} broke after two days. Do you need photos for the return?",
    "I think I was charged the wrong price for the {product} in {order}.",
)
OPS_FLAGS = (
    ("delivery", "Several customers in the {region} say their {carrier} parcels are days past the promised date."),
    ("delivery", "Two customers got parcels from {carrier} that were crushed, both in the {region}."),
    (
        "delivery",
        "Tracking for {carrier} parcels to the {region} has not updated since yesterday, per three customers.",
    ),
    (
        "product",
        "Customers say the {product} is listed as available, but their orders for it have not shipped for a week.",
    ),
    ("payments", "Three customers were charged twice for the same order this morning."),
    (
        "delivery",
        "Parcels marked delivered by {carrier} in the {region} never arrived, according to several customers.",
    ),
    ("other", "Orders placed since yesterday are stuck in pending much longer than usual."),
)
INSIGHTS_FLAGS = (
    ("policy", "Customers keep asking whether they can exchange an item for a different product, not just a variant."),
    ("policy", "Several customers are confused that refunds for gift card orders go back to the gift card."),
    ("product", "Customers ask again and again whether the {battery} works with Google Home; the guide doesn't say."),
    ("product", "Buyers of the {appliance} say the setup instructions are confusing and ask the same steps."),
    ("policy", "Customers don't understand why a pending order can only have its items changed once."),
    ("account", "Many customers ask how to update their default address before ordering; the help article is unclear."),
    ("product", "Customers suggest the {product} should come in more sizes; several asked this week."),
    ("other", "Customers ask whether there is a loyalty program; nothing in the help center answers it."),
)
HUMAN_FLAGS = (
    ("product", "Two customers report the {battery} battery overheating while charging."),
    ("product", "Three customers say the {appliance} tripped their circuit breaker and smelled of burning plastic."),
    ("other", "Several customers mention a class action lawsuit about our delivery fees."),
    ("account", "Customers report orders appearing on their accounts that they never placed."),
    ("other", "A journalist has contacted several customers and they are asking whether we will comment."),
)


class DispatcherEvalReport(StrictModel):
    profile: str
    started_at: datetime
    scores: DispatcherScores
    decisions: dict[str, RouteDecision]
    cost_usd: float
    stopped_at_cap: bool


def load_cases(path: Path) -> list[DispatcherCase]:
    return [DispatcherCase.model_validate(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def write_cases(path: Path, cases: Sequence[DispatcherCase]) -> None:
    path.write_text("".join(case.model_dump_json() + "\n" for case in cases))


def build_cases(store: RetailSnapshot, *, seed: int = 11) -> list[DispatcherCase]:
    draw = rng(seed, "dispatcher")
    orders = sorted(store.orders)
    products = sorted({product.name for product in store.products.values()})

    def fill(template: str) -> str:
        first, other = draw.sample(orders, 2)
        return template.format(
            order=first,
            other=other,
            product=draw.choice(products),
            battery=draw.choice(BATTERY_PRODUCTS),
            appliance=draw.choice(APPLIANCES),
            carrier=draw.choice(CARRIERS),
            region=draw.choice(REGIONS),
        )

    cases: list[DispatcherCase] = []

    def add(kind: str, brief: str, route: str, *, several: bool = False, note: str = "") -> None:
        case = {"case_id": f"dc_{len(cases):03d}", "kind": kind, "brief": brief, "route": route}
        cases.append(DispatcherCase.model_validate({**case, "several_issues": several, "note": note}))

    for brief in make_briefs(store, NORMAL_MIX, 90, seed=seed):
        add("ticket", f"Subject: {brief.subject}\n\n{brief.opening_message}", "support", note=brief.intent)
    for template, several in HARD_SUPPORT:
        add("ticket", f"Subject: Help\n\n{fill(template)}", "support", several=several, note="edge case for support")
    for template in NOT_FOR_A_PERSON:
        add("ticket", f"Subject: Help\n\n{fill(template)}", "support", note="sounds serious, but support handles it")
    for note, templates in (
        ("safety", SAFETY),
        ("legal", LEGAL),
        ("press", PRESS),
        ("privacy", PRIVACY),
        ("threat", THREATS),
        ("fraud", FRAUD),
    ):
        for template in templates:
            add("ticket", f"Subject: Urgent\n\n{fill(template)}", "human", note=note)
    for index in range(20):
        add("alert", alert_brief(_alert(draw, index)), "ops", note="delivery watch")
    for product in draw.sample(BATTERY_PRODUCTS + APPLIANCES, 5):
        add("alert", alert_brief(_safety_alert(product)), "human", note="safety reports")
    for route, flags in (("ops", OPS_FLAGS), ("insights", INSIGHTS_FLAGS), ("human", HUMAN_FLAGS)):
        repeats = 2 if route != "human" else 1
        for topic, summary in [flag for flag in flags for _ in range(repeats)][:15]:
            flag = PatternFlag.model_validate({"topic": topic, "summary": fill(summary), "ticket_ids": _tickets(draw)})
            add("flag", flag_brief(flag, "support", f"wi_{draw.randrange(16**8):08x}"), route, note=topic)
    return cases


def _alert(draw: random.Random, index: int) -> KpiAlert:
    observed = 4 + index % 5
    expected = round(0.3 + (index % 4) * 0.2, 2)
    return KpiAlert(
        metric="where_is_my_order_tickets",
        segment={"carrier": draw.choice(CARRIERS), "region": draw.choice(REGIONS)},
        window_hours=3,
        value=observed,
        baseline=expected,
        z_score=round((observed - expected) / max(expected, 0.5) ** 0.5, 2),
        ratio=round(observed / expected, 2),
        samples=observed + 6,
        detected_at=RAISED_AT,
    )


def _safety_alert(product: str) -> KpiAlert:
    return KpiAlert(
        metric="product_safety_reports",
        segment={"product": product},
        window_hours=24,
        value=4,
        baseline=0.1,
        z_score=8.9,
        ratio=40.0,
        samples=4,
        detected_at=RAISED_AT,
    )


def _tickets(draw: random.Random) -> list[str]:
    return [f"tk_{draw.randrange(10**6):06d}" for _ in range(1 + draw.randrange(3))]


async def run_dispatcher_eval(
    models: ChatModels,
    cases: Sequence[DispatcherCase],
    *,
    profile: str,
    started_at: datetime,
    max_usd: float,
    concurrency: int = 8,
    spec: AgentSpec = DISPATCHER,
) -> DispatcherEvalReport:
    decisions: dict[str, RouteDecision] = {}
    spent = 0.0
    model = models.model_key(spec.role, spec.model)
    for start in range(0, len(cases), concurrency):
        if spent >= max_usd:
            break
        batch = cases[start : start + concurrency]
        results = await asyncio.gather(
            *(decide_route(models, spec, case.kind, case.brief, TODAY, model=model) for case in batch)
        )
        for case, (decision, report) in zip(batch, results, strict=True):
            decisions[case.case_id] = decision
            if report is not None:
                spent += report.cost_usd(models.price(spec.role, model))
    decided = [case for case in cases if case.case_id in decisions]
    return DispatcherEvalReport(
        profile=profile,
        started_at=started_at,
        scores=score_dispatcher(decided, [decisions[case.case_id] for case in decided]),
        decisions=decisions,
        cost_usd=round(spent, 6),
        stopped_at_cap=len(decided) < len(cases),
    )

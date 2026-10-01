from __future__ import annotations

from urllib.parse import quote

from ahq.app.container import Overrides
from ahq.domain.retail import RetailSnapshot
from tests.e2e.conftest import OPERATOR, running
from tests.e2e.test_simulator_api import seeded


async def test_the_admin_reads_an_order_with_its_parcels_and_its_customer(tau3_snapshot: RetailSnapshot) -> None:
    async with running(Overrides(store=tau3_snapshot)) as run:
        await seeded(run, tau3_snapshot)
        shipped = next(order for order in tau3_snapshot.orders.values() if order.fulfillments)
        path = f"/api/store/orders/{quote(shipped.order_id)}"

        assert (await run.http.get(path)).status_code == 401
        view = (await run.http.get(path, headers=OPERATOR)).json()
        assert view["order"]["order_id"] == shipped.order_id
        assert view["shipments"]
        assert {shipment["order_id"] for shipment in view["shipments"]} == {shipped.order_id}

        customer = await run.http.get(f"/api/store/customers/{shipped.user_id}", headers=OPERATOR)
        assert shipped.order_id in customer.json()["orders"]

        assert (await run.http.get(f"/api/store/orders/{quote('#W0000000')}", headers=OPERATOR)).status_code == 404
        assert (await run.http.get("/api/store/customers/nobody_0000", headers=OPERATOR)).status_code == 404

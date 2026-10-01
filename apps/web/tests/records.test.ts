import { describe, expect, it } from "vitest"

import type { AhqEvent, Order, Shipment } from "@/lib/api/types"
import { version, versionsIn } from "@/lib/format"
import type { Prepared } from "@/lib/recording/derive"
import { pieces } from "@/lib/records/ids"
import { orderStatusAt, orderStory, parcelAt } from "@/lib/records/view"

const ORDER = "#W4817420"
let nextId = 1

function event(
  kind: AhqEvent["kind"],
  payload: Record<string, unknown>
): AhqEvent {
  return {
    id: nextId++,
    kind,
    occurred_at: "2026-06-15T12:00:00Z",
    recorded_at: "2026-09-28T15:00:00Z",
    actor: "support",
    work_item_id: "wi_1",
    payload,
  }
}

function day(events: AhqEvent[]): Prepared {
  return {
    events,
    recording: { incidents: [], approvals: [], store: {} },
    work: new Map(),
  } as unknown as Prepared
}

function order(status: Order["status"]): Order {
  return {
    order_id: ORDER,
    user_id: "ava_moore_6020",
    address: {
      address1: "1 Main St",
      address2: "",
      city: "Phoenix",
      country: "USA",
      state: "AZ",
      zip: "85002",
    },
    items: [],
    status,
    fulfillments: [],
    payment_history: [],
  }
}

describe("record IDs in text", () => {
  it("finds orders, customers and tickets, and nothing in an email address", () => {
    expect(
      pieces(
        `Order ${ORDER} for ava_moore_6020, tk_7_0012; ava.moore6020@example.com`
      )
    ).toEqual([
      "Order ",
      { kind: "order", id: ORDER },
      " for ",
      { kind: "customer", id: "ava_moore_6020" },
      ", ",
      { kind: "ticket", id: "tk_7_0012" },
      "; ava.moore6020@example.com",
    ])
  })
})

describe("an order at a moment of the day", () => {
  it("was what the day first showed it as, and then what each change made it", () => {
    const read = event("tool.called", {
      tool: "get_order_details",
      ok: true,
      verdict: "allowed",
      arguments: { order_id: ORDER },
      result: { order_id: ORDER, status: "delivered" },
    })
    const returned = event("tool.called", {
      tool: "return_delivered_order_items",
      ok: true,
      verdict: "approved",
      arguments: { order_id: ORDER },
      result: { order_id: ORDER, status: "return requested" },
    })
    const recorded = day([read, returned])
    const final = order("return requested")
    expect(orderStatusAt(recorded, final, read.id - 1)).toBe("delivered")
    expect(orderStatusAt(recorded, final, read.id)).toBe("delivered")
    expect(orderStatusAt(recorded, final, returned.id)).toBe("return requested")
  })

  it("was pending before it shipped, and processed until it arrived", () => {
    const shipped = event("order.shipped", {
      order_id: ORDER,
      carrier: "northstar",
    })
    const delivered = event("parcel.delivered", {
      order_id: ORDER,
      carrier: "northstar",
    })
    const recorded = day([shipped, delivered])
    const final = order("delivered")
    expect(orderStatusAt(recorded, final, shipped.id - 1)).toBe("pending")
    expect(orderStatusAt(recorded, final, shipped.id)).toBe("processed")
    expect(orderStatusAt(recorded, final, delivered.id)).toBe("delivered")
  })

  it("tells what happened to it, up to the moment", () => {
    const opened = event("ticket.opened", {
      ticket_id: "tk_7_0001",
      order_id: ORDER,
      subject: "Where is my order?",
    })
    const refused = event("tool.called", {
      tool: "cancel_pending_order",
      agent: "support",
      ok: false,
      verdict: "refused",
      reason: "the order is not pending",
      arguments: { order_id: ORDER },
    })
    const shipped = event("order.shipped", {
      order_id: ORDER,
      carrier: "northstar",
    })
    const recorded = day([opened, refused, shipped])
    const story = orderStory(recorded, ORDER, refused.id)
    expect(story.map((line) => line.text)).toEqual([
      "A customer wrote in: Where is my order?",
      "Support was refused cancel pending order: the order is not pending",
    ])
    expect(story[0].ticketId).toBe("tk_7_0001")
    expect(story[1].tone).toBe("refused")
  })
})

describe("a parcel at a moment of the day", () => {
  const parcel: Shipment = {
    tracking_id: "187702030350",
    order_id: ORDER,
    carrier: "northstar",
    state: "AZ",
    region: "west",
    status: "delivered",
    shipped_at: "2026-06-10T12:00:00Z",
    promised_at: "2026-06-14T12:00:00Z",
    delivered_at: "2026-06-15T12:00:00Z",
  }
  it("is not shipped, in transit, then delivered, late when after its promise", () => {
    expect(parcelAt(parcel, Date.parse("2026-06-09T12:00:00Z"))).toBe(
      "not shipped yet"
    )
    expect(parcelAt(parcel, Date.parse("2026-06-12T12:00:00Z"))).toBe(
      "in transit"
    )
    expect(parcelAt(parcel, Date.parse("2026-06-16T12:00:00Z"))).toBe(
      "delivered, late"
    )
  })
})

describe("agent versions for people", () => {
  it("read support@2 as support v2, alone or in a sentence", () => {
    expect(version("support@2")).toBe("support v2")
    expect(versionsIn("support@2 on 60%, replacing support@1")).toBe(
      "support v2 on 60%, replacing support v1"
    )
    expect(versionsIn("ava.moore6020@example.com")).toBe(
      "ava.moore6020@example.com"
    )
  })
})

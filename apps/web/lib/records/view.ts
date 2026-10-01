import type {
  AhqEvent,
  Customer,
  Order,
  Shipment,
  Ticket,
} from "@/lib/api/types"
import { type Prepared, runAt } from "@/lib/recording/derive"

const NEEDS: Record<string, string> = {
  cancel_pending_order: "pending",
  modify_pending_order_items: "pending",
  modify_pending_order_address: "pending",
  modify_pending_order_payment: "pending",
  return_delivered_order_items: "delivered",
  exchange_delivered_order_items: "delivered",
}

const AGENTS: Record<string, string> = {
  dispatcher: "The Dispatcher",
  support: "Support",
  ops: "Ops",
  insights: "Insights",
}

type Seen = { at: number; status: string; before: string }

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function orderOfCall(event: AhqEvent): string | null {
  const named =
    record(event.payload?.arguments).order_id ??
    record(event.payload?.result).order_id
  return typeof named === "string" ? named : null
}

export function aboutOrder(event: AhqEvent, id: string): boolean {
  if (event.kind === "tool.called") {
    return orderOfCall(event) === id
  }
  return event.payload?.order_id === id
}

function sightings(prepared: Prepared, id: string): Seen[] {
  const seen: Seen[] = []
  for (const event of prepared.events) {
    if (!aboutOrder(event, id)) {
      continue
    }
    if (event.kind === "order.shipped") {
      seen.push({ at: event.id, status: "processed", before: "pending" })
    } else if (event.kind === "parcel.delivered") {
      seen.push({ at: event.id, status: "delivered", before: "processed" })
    } else if (event.kind === "tool.called" && event.payload?.ok) {
      const status = record(event.payload?.result).status
      if (typeof status === "string") {
        const tool = String(event.payload?.tool)
        seen.push({ at: event.id, status, before: NEEDS[tool] ?? status })
      }
    }
  }
  return seen
}

export function orderStatusAt(
  prepared: Prepared,
  order: Order,
  cursor: number
): string {
  const seen = sightings(prepared, order.order_id)
  const last = seen.findLast((sighting) => sighting.at <= cursor)
  return last?.status ?? seen[0]?.before ?? order.status
}

export function parcelAt(shipment: Shipment, now: number): string {
  const at = (iso?: string | null) => (iso ? Date.parse(iso) : null)
  const delivered = at(shipment.delivered_at)
  const shipped = at(shipment.shipped_at)
  if (delivered !== null && delivered <= now) {
    const promised = at(shipment.promised_at)
    return promised !== null && delivered > promised
      ? "delivered, late"
      : "delivered"
  }
  if (shipped !== null && shipped <= now) {
    return "in transit"
  }
  return "not shipped yet"
}

export type StoryLine = {
  event: AhqEvent
  text: string
  tone?: "refused" | "waiting"
  ticketId?: string
  incidentId?: string
}

export function orderStory(
  prepared: Prepared,
  id: string,
  cursor: number
): StoryLine[] {
  const lines: StoryLine[] = []
  const incidents = new Set(
    prepared.recording.incidents
      .filter((incident) =>
        incident.record.report.affected.order_ids.includes(id)
      )
      .map((incident) => incident.record.incident_id)
  )
  const waits = new Map(
    prepared.recording.approvals
      .filter((approval) => {
        const named = record(approval.pending.request.arguments).order_id
        return named === id
      })
      .map((approval) => [approval.pending.id, approval])
  )
  for (const event of prepared.events) {
    if (event.id > cursor) {
      break
    }
    const payload = event.payload ?? {}
    if (event.kind === "ticket.opened" && payload.order_id === id) {
      lines.push({
        event,
        text: `A customer wrote in: ${String(payload.subject ?? "")}`,
        ticketId: String(payload.ticket_id),
      })
    } else if (event.kind === "tool.called" && orderOfCall(event) === id) {
      const agent = AGENTS[String(payload.agent)] ?? "An agent"
      const tool = String(payload.tool).replaceAll("_", " ")
      const status = record(payload.result).status
      if (payload.verdict === "refused") {
        lines.push({
          event,
          text: `${agent} was refused ${tool}: ${String(payload.reason ?? "")}`,
          tone: "refused",
        })
      } else if (!payload.ok) {
        lines.push({ event, text: `${agent} tried ${tool}, which failed` })
      } else {
        const approved = payload.verdict === "approved" ? ", approved" : ""
        const now = typeof status === "string" ? `; now ${status}` : ""
        lines.push({ event, text: `${agent} ran ${tool}${approved}${now}` })
      }
    } else if (event.kind === "approval.requested") {
      const approval = waits.get(String(payload.approval_id))
      if (approval) {
        lines.push({
          event,
          text: `Waited for a person to approve: ${approval.pending.request.action.replaceAll("_", " ")}`,
          tone: "waiting",
        })
      }
    } else if (event.kind === "order.shipped" && payload.order_id === id) {
      lines.push({ event, text: `Shipped with ${String(payload.carrier)}` })
    } else if (event.kind === "parcel.delivered" && payload.order_id === id) {
      const late = payload.late ? ", late" : ""
      lines.push({
        event,
        text: `Delivered by ${String(payload.carrier)}${late}`,
      })
    } else if (
      event.kind === "incident.filed" &&
      incidents.has(String(payload.incident_id))
    ) {
      lines.push({
        event,
        text: "Ops named it in an incident",
        incidentId: String(payload.incident_id),
      })
    }
  }
  return lines
}

export function customerOrders(
  prepared: Prepared,
  customer: Customer,
  cursor: number
): { id: string; status: string | null }[] {
  const known = new Map(
    (prepared.recording.store?.orders ?? []).map((order) => [
      order.order_id,
      order,
    ])
  )
  return customer.orders.map((id) => {
    const order = known.get(id)
    return { id, status: order ? orderStatusAt(prepared, order, cursor) : null }
  })
}

function openedAt(prepared: Prepared, id: string): AhqEvent | undefined {
  return prepared.events.find(
    (event) => event.kind === "ticket.opened" && event.payload?.ticket_id === id
  )
}

export function customerTickets(
  prepared: Prepared,
  customerId: string,
  cursor: number
): Ticket[] {
  return (prepared.recording.store?.tickets ?? []).filter((ticket) => {
    const opened = openedAt(prepared, ticket.ticket_id)
    return (
      ticket.user_id === customerId &&
      opened !== undefined &&
      opened.id <= cursor
    )
  })
}

export function ticketStanding(
  prepared: Prepared,
  id: string,
  cursor: number
): { ticket: Ticket; workItemId: string | null } | null {
  const stored = (prepared.recording.store?.tickets ?? []).find(
    (ticket) => ticket.ticket_id === id
  )
  const opened = openedAt(prepared, id)
  if (!stored || !opened || opened.id > cursor) {
    return null
  }
  const work = [...prepared.work.values()].find(
    (candidate) => candidate.item.input?.ticket_id === id
  )
  if (work) {
    const run = runAt(prepared, cursor, work.item.id)
    return { ticket: run?.run.ticket ?? stored, workItemId: work.item.id }
  }
  return {
    ticket: {
      ...stored,
      status: "open",
      messages: stored.messages.slice(0, 1),
    },
    workItemId: null,
  }
}

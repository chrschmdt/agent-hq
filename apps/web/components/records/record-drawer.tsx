"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { readCustomer, readOrder, readTicket } from "@/app/actions"
import {
  useDay,
  useMoment,
  useRecorded,
} from "@/components/recording/recording-provider"
import {
  DrawerBody,
  DrawerHeader,
  DrawerLink,
  useDrawer,
} from "@/components/shell/drawer-context"
import { Badge } from "@/components/ui/badge"
import type {
  Customer,
  Order,
  OrderView,
  Shipment,
  Ticket,
} from "@/lib/api/types"
import { clock, moment, usd, words } from "@/lib/format"
import { KIND_NAMES, pieces, type RecordRef } from "@/lib/records/ids"
import {
  customerOrders,
  customerTickets,
  orderStatusAt,
  orderStory,
  parcelAt,
  type StoryLine,
  ticketStanding,
} from "@/lib/records/view"
import { cn } from "@/lib/utils"

export function RecordLink({
  target,
  children,
}: {
  target: RecordRef
  children?: React.ReactNode
}) {
  const { open } = useDrawer()
  return (
    <button
      type="button"
      onClick={() => open(target)}
      className={cn(
        "cursor-pointer text-left text-foreground underline decoration-muted-foreground/60 decoration-dotted underline-offset-[3px] hover:decoration-foreground",
        children === undefined && "font-mono text-[0.95em]"
      )}
    >
      {children ?? target.id}
    </button>
  )
}

export function LinkedText({ text }: { text: string }) {
  return (
    <>
      {pieces(text).map((piece, index) =>
        typeof piece === "string" ? (
          piece
        ) : (
          <RecordLink key={`${index}:${piece.id}`} target={piece} />
        )
      )}
    </>
  )
}

export function RecordPanel({ target }: { target: RecordRef }) {
  return (
    <>
      <DrawerHeader
        title={
          <>
            {KIND_NAMES[target.kind]}
            <span className="font-mono text-sm font-normal text-muted-foreground">
              {target.id}
            </span>
          </>
        }
        description={`The ${target.kind} as it stood at this moment of the day.`}
        hideDescription
      />
      <DrawerBody className="sm:p-4">
        {target.kind === "order" ? (
          <OrderPanel id={target.id} />
        ) : target.kind === "customer" ? (
          <CustomerPanel id={target.id} />
        ) : (
          <TicketPanel id={target.id} />
        )}
      </DrawerBody>
    </>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}

function Missing({ what }: { what: string }) {
  return (
    <p className="text-muted-foreground">
      {what} is not in this recorded day. Days recorded before drawers existed
      hold no records.
    </p>
  )
}

function Loading({ failed }: { failed: boolean }) {
  return (
    <p className="text-muted-foreground">
      {failed ? "Could not load it." : "Loading."}
    </p>
  )
}

function useLive<T>(
  key: string,
  id: string,
  enabled: boolean,
  read: (
    id: string
  ) => Promise<{ ok: true; data: T } | { ok: false; error: string }>
) {
  return useQuery({
    queryKey: ["record", key, id],
    queryFn: async () => {
      const result = await read(id)
      if (!result.ok) {
        throw new Error(result.error)
      }
      return result.data
    },
    enabled,
    staleTime: 10_000,
  })
}

function OrderPanel({ id }: { id: string }) {
  const day = useDay()
  const now = useMoment() ?? Number.POSITIVE_INFINITY
  const recorded = useRecorded((prepared, cursor) => {
    const store = prepared.recording.store
    const order = store?.orders?.find((candidate) => candidate.order_id === id)
    if (!store || !order) {
      return null
    }
    return {
      order,
      status: orderStatusAt(prepared, order, cursor),
      shipments: (store.shipments ?? []).filter(
        (parcel) => parcel.order_id === id
      ),
      customer: (store.customers ?? []).find(
        (c) => c.user_id === order.user_id
      ),
      story: orderStory(prepared, id, cursor),
    }
  })
  const live = useLive<OrderView>("order", id, !recorded.recording, readOrder)
  if (recorded.recording) {
    if (!recorded.data) {
      return <Missing what="This order" />
    }
    const { order, status, shipments, customer, story } = recorded.data
    return (
      <OrderBody
        order={order}
        status={status}
        shipments={shipments}
        customer={customer}
        now={now}
        story={story}
        day={day}
      />
    )
  }
  if (!live.data) {
    return <Loading failed={live.isError} />
  }
  return (
    <OrderBody
      order={live.data.order}
      status={live.data.order.status}
      shipments={live.data.shipments}
      now={now}
      day={day}
    />
  )
}

function OrderBody({
  order,
  status,
  shipments,
  customer,
  now,
  story,
  day,
}: {
  order: Order
  status: string
  shipments: Shipment[]
  customer?: Customer
  now: number
  story?: StoryLine[]
  day: (iso: string) => string
}) {
  const total = order.items.reduce((sum, item) => sum + item.price, 0)
  const settled = status === order.status
  const payments = order.payment_history.filter(
    (entry) => settled || entry.transaction_type === "payment"
  )
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{status}</Badge>
        <span className="text-muted-foreground">for</span>
        <RecordLink target={{ kind: "customer", id: order.user_id }}>
          {customer
            ? `${customer.name.first_name} ${customer.name.last_name}`
            : order.user_id}
        </RecordLink>
      </div>
      <Section title="Items">
        <ul className="flex flex-col divide-y rounded-lg border">
          {order.items.map((item, index) => (
            <li
              key={`${item.item_id}:${index}`}
              className="flex items-baseline justify-between gap-3 px-3 py-2"
            >
              <span className="min-w-0">
                <span className="font-medium">{item.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {Object.values(item.options).join(", ")}
                </span>
              </span>
              <span className="shrink-0 tabular-nums">{usd(item.price)}</span>
            </li>
          ))}
          <li className="flex justify-between px-3 py-2 font-medium">
            <span>Total</span>
            <span className="tabular-nums">{usd(total)}</span>
          </li>
        </ul>
      </Section>
      {shipments.length > 0 ? (
        <Section title="Parcels">
          {shipments.map((parcel) => (
            <div
              key={parcel.tracking_id}
              className="flex flex-col gap-0.5 rounded-lg border px-3 py-2"
            >
              <span className="flex items-baseline justify-between gap-3">
                <span className="capitalize">{parcel.carrier}</span>
                <span className="text-xs text-muted-foreground">
                  {parcelAt(parcel, now)}
                </span>
              </span>
              <span className="font-mono text-xs text-muted-foreground">
                {parcel.tracking_id}
              </span>
              <span className="text-xs text-muted-foreground">
                {[
                  parcel.shipped_at && Date.parse(parcel.shipped_at) <= now
                    ? `shipped ${moment(parcel.shipped_at)}`
                    : null,
                  parcel.promised_at
                    ? `due ${moment(parcel.promised_at)}`
                    : null,
                  parcel.delivered_at && Date.parse(parcel.delivered_at) <= now
                    ? `delivered ${moment(parcel.delivered_at)}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
          ))}
        </Section>
      ) : null}
      <Section title="Ship to">
        <p className="text-muted-foreground">
          {[
            order.address.address1,
            order.address.address2,
            `${order.address.city}, ${order.address.state} ${order.address.zip}`,
          ]
            .filter(Boolean)
            .join(", ")}
        </p>
      </Section>
      {payments.length > 0 ? (
        <Section title="Payments">
          <ul className="flex flex-col gap-1">
            {payments.map((entry, index) => (
              <li
                key={`${entry.payment_method_id}:${index}`}
                className="flex justify-between gap-3"
              >
                <span className="text-muted-foreground">
                  {entry.transaction_type === "refund"
                    ? "Refund to"
                    : "Paid by"}{" "}
                  {words(entry.payment_method_id)}
                </span>
                <span className="tabular-nums">{usd(entry.amount)}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {story ? (
        <Section title="During the day">
          {story.length === 0 ? (
            <p className="text-muted-foreground">Nothing yet.</p>
          ) : (
            <ol className="flex flex-col gap-2">
              {story.map((line) => (
                <li
                  key={line.event.id}
                  className="grid grid-cols-[3rem_minmax(0,1fr)] gap-2"
                >
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">
                    {clock(
                      day(line.event.recorded_at ?? line.event.occurred_at)
                    )}
                  </span>
                  <span
                    className={
                      line.tone === "refused"
                        ? "text-[var(--map-red)]"
                        : line.tone === "waiting"
                          ? "text-[var(--map-amber)]"
                          : undefined
                    }
                  >
                    {line.text}
                    {line.ticketId ? (
                      <>
                        {" "}
                        <RecordLink
                          target={{ kind: "ticket", id: line.ticketId }}
                        />
                      </>
                    ) : null}
                    {line.incidentId ? (
                      <>
                        {" "}
                        <DrawerLink
                          target={{ kind: "incident", id: line.incidentId }}
                          className="underline underline-offset-2"
                        >
                          Open it
                        </DrawerLink>
                      </>
                    ) : null}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>
      ) : null}
    </>
  )
}

function CustomerPanel({ id }: { id: string }) {
  const recorded = useRecorded((prepared, cursor) => {
    const customer = prepared.recording.store?.customers?.find(
      (candidate) => candidate.user_id === id
    )
    if (!customer) {
      return null
    }
    return {
      customer,
      orders: customerOrders(prepared, customer, cursor),
      tickets: customerTickets(prepared, id, cursor),
    }
  })
  const live = useLive<Customer>(
    "customer",
    id,
    !recorded.recording,
    readCustomer
  )
  if (recorded.recording && !recorded.data) {
    return <Missing what="This customer" />
  }
  const customer = recorded.data?.customer ?? live.data
  if (!customer) {
    return <Loading failed={live.isError} />
  }
  const orders =
    recorded.data?.orders ??
    customer.orders.map((order) => ({ id: order, status: null }))
  return (
    <>
      <div className="flex flex-col gap-0.5">
        <span className="text-base font-medium">
          {customer.name.first_name} {customer.name.last_name}
        </span>
        <span className="text-muted-foreground">{customer.email}</span>
        <span className="text-muted-foreground">
          {customer.address.city}, {customer.address.state}
        </span>
      </div>
      <Section title="Payment methods">
        <ul className="flex flex-col gap-1">
          {Object.values(customer.payment_methods).map((method) => (
            <li key={method.id} className="flex justify-between gap-3">
              <span>
                {method.source === "credit_card"
                  ? `${method.brand.charAt(0).toUpperCase()}${method.brand.slice(1)} ending ${method.last_four}`
                  : method.source === "gift_card"
                    ? "Gift card"
                    : "PayPal"}
              </span>
              {method.source === "gift_card" ? (
                <span className="text-muted-foreground tabular-nums">
                  {usd(method.balance)} left
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Orders">
        <ul className="flex flex-col gap-1">
          {orders.map((order) => (
            <li key={order.id} className="flex justify-between gap-3">
              <RecordLink target={{ kind: "order", id: order.id }} />
              {order.status ? (
                <span className="text-muted-foreground">{order.status}</span>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>
      {recorded.data && recorded.data.tickets.length > 0 ? (
        <Section title="Tickets during the day">
          <ul className="flex flex-col gap-1">
            {recorded.data.tickets.map((ticket) => (
              <li key={ticket.ticket_id} className="flex flex-col items-start">
                <RecordLink target={{ kind: "ticket", id: ticket.ticket_id }} />
                <span className="text-muted-foreground">{ticket.subject}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </>
  )
}

function TicketPanel({ id }: { id: string }) {
  const day = useDay()
  const recorded = useRecorded((prepared, cursor) =>
    ticketStanding(prepared, id, cursor)
  )
  const live = useLive<Ticket>("ticket", id, !recorded.recording, readTicket)
  if (recorded.recording && !recorded.data) {
    return (
      <p className="text-muted-foreground">
        This ticket is not in the recorded day, or has not been opened yet at
        this moment.
      </p>
    )
  }
  const ticket = recorded.data?.ticket ?? live.data
  if (!ticket) {
    return <Loading failed={live.isError} />
  }
  const workItemId = recorded.data?.workItemId ?? null
  return (
    <>
      <div className="flex flex-col gap-2">
        <span className="text-base font-medium">{ticket.subject}</span>
        <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
          <Badge variant="outline">{words(ticket.status)}</Badge>
          <span>{words(ticket.intent)}</span>
          {ticket.user_id ? (
            <RecordLink target={{ kind: "customer", id: ticket.user_id }} />
          ) : null}
          {ticket.order_id ? (
            <RecordLink target={{ kind: "order", id: ticket.order_id }} />
          ) : null}
        </div>
        {workItemId ? (
          <Link
            href={`/runs/${workItemId}`}
            className="w-fit text-[var(--map-live)] underline-offset-4 hover:underline"
          >
            Open the run the agents handled it in
          </Link>
        ) : recorded.recording ? (
          <p className="text-muted-foreground">
            The agents were not handed this ticket. It is background traffic,
            which the store watches for trouble.
          </p>
        ) : null}
      </div>
      <Section title="Conversation">
        <ol className="flex flex-col gap-3">
          {ticket.messages.map((message, index) => (
            <li key={index} className="flex flex-col gap-0.5">
              <span className="text-xs text-muted-foreground">
                {message.author === "customer"
                  ? "Customer"
                  : message.author === "agent"
                    ? "Support"
                    : "Store"}
                , {clock(day(message.created_at))}
              </span>
              <p className="whitespace-pre-wrap">
                <LinkedText text={message.body} />
              </p>
            </li>
          ))}
        </ol>
      </Section>
    </>
  )
}

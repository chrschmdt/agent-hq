export type RecordKind = "order" | "customer" | "ticket"
export type RecordRef = { kind: RecordKind; id: string }
export type Piece = string | RecordRef

const PATTERN =
  /(#W\d{7})|\b(tk_[a-z0-9]+(?:_[a-z0-9]+)*)\b|\b([a-z]+_[a-z]+_\d{4})\b/g

export function pieces(text: string): Piece[] {
  const out: Piece[] = []
  let last = 0
  for (const match of text.matchAll(PATTERN)) {
    const at = match.index
    if (at > last) {
      out.push(text.slice(last, at))
    }
    const [whole, order, ticket, customer] = match
    out.push(
      order
        ? { kind: "order", id: order }
        : ticket
          ? { kind: "ticket", id: ticket }
          : { kind: "customer", id: customer }
    )
    last = at + whole.length
  }
  if (last < text.length) {
    out.push(text.slice(last))
  }
  return out
}

export const KIND_NAMES: Record<RecordKind, string> = {
  order: "Order",
  customer: "Customer",
  ticket: "Ticket",
}

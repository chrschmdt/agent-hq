import type { AhqEvent, ProposalRecord } from "@/lib/api/types"
import type { DetailRef } from "@/lib/drawer"
import { list, record, text } from "@/lib/scene/payload"

import { name } from "./passes"

export const LATER_KINDS = ["ticket.replied", "kb.published"] as const

export type ChainTone = "alert" | "agent" | "you" | "published" | "cited"

export type ChainLink =
  { href: string; label: string } | { target: DetailRef; label: string }

export type ChainStep = {
  at: number
  tone: ChainTone
  title: string
  detail: string | null
  links: ChainLink[]
}

function time(event: AhqEvent): number {
  return Date.parse(event.recorded_at ?? event.occurred_at)
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`
}

function clip(value: string | null, limit = 240): string | null {
  if (value === null) {
    return null
  }
  return value.length <= limit ? value : `${value.slice(0, limit - 3)}...`
}

function counted(tools: string[]): string {
  const counts = new Map<string, number>()
  for (const tool of tools) {
    counts.set(tool, (counts.get(tool) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([tool, n]) => (n > 1 ? `${tool} x${n}` : tool))
    .join(", ")
}

export function incidentChain(
  runEvents: readonly AhqEvent[],
  later: readonly AhqEvent[],
  proposals: readonly ProposalRecord[]
): ChainStep[] {
  const events = [...runEvents].sort((a, b) => a.id - b.id)
  if (events.length === 0) {
    return []
  }
  const origin = time(events[0])
  const at = (event: AhqEvent) => time(event) - origin
  const steps: ChainStep[] = []
  const titles = new Map(
    proposals.map((p) => [p.proposal_id, p.proposal.title])
  )

  const routed = events.find((event) => event.kind === "work.routed")
  steps.push({
    at: 0,
    tone: "alert",
    title:
      "The hourly delivery check raised an alert, and it became work for the team",
    detail: routed
      ? `The Dispatcher sent it to ${name(text(routed.payload, "route") ?? "ops")}: ${text(routed.payload, "reason") ?? ""}`
      : null,
    links: [],
  })

  const investigation = (agent: string, until: number) => {
    const calls = events.filter(
      (e) => e.kind === "tool.called" && e.actor === agent && e.id < until
    )
    const models = events.filter(
      (e) => e.kind === "model.called" && e.actor === agent && e.id < until
    )
    return { calls, models }
  }

  const filed = events.find((e) => e.kind === "incident.filed")
  if (filed) {
    const { calls, models } = investigation("ops", filed.id)
    if (models.length > 0) {
      steps.push({
        at: at(models[0]),
        tone: "agent",
        title: `Ops looked into it: ${plural(models.length, "model call")}, ${plural(calls.length, "tool call")}`,
        detail: calls.length
          ? counted(calls.map((c) => text(c.payload, "tool") ?? "tool"))
          : null,
        links: [],
      })
    }
    steps.push({
      at: at(filed),
      tone: "agent",
      title: `Ops filed the incident: ${text(filed.payload, "title") ?? ""}`,
      detail: `Severity ${text(filed.payload, "severity") ?? "unknown"}.`,
      links: [],
    })
  }

  for (const handoff of events.filter((e) => e.kind === "agent.handoff")) {
    const to = text(handoff.payload, "to") ?? ""
    steps.push({
      at: at(handoff),
      tone: to === "human" ? "you" : "agent",
      title: `${name(text(handoff.payload, "from") ?? "")} handed it to ${to === "human" ? "a person" : name(to)}`,
      detail: clip(text(handoff.payload, "brief")),
      links: [],
    })
  }

  const insightsCalls = events.filter(
    (e) => e.kind === "tool.called" && e.actor === "insights"
  )
  if (insightsCalls.length > 0) {
    const drafted = insightsCalls
      .filter((e) => text(e.payload, "tool") === "knowledge_draft_article")
      .map((e) => text(record(e.payload, "arguments") ?? {}, "doc_id"))
      .filter((doc): doc is string => doc !== null)
    steps.push({
      at: at(insightsCalls[0]),
      tone: "agent",
      title: `Insights worked on it: ${plural(insightsCalls.length, "tool call")}`,
      detail: [
        counted(insightsCalls.map((c) => text(c.payload, "tool") ?? "tool")),
        drafted.length ? `drafted ${drafted.join(", ")}` : "",
      ]
        .filter(Boolean)
        .join("; "),
      links: [],
    })
  }
  for (const created of events.filter((e) => e.kind === "proposal.created")) {
    const id = text(created.payload, "proposal_id") ?? ""
    steps.push({
      at: at(created),
      tone: "agent",
      title: `Insights proposed: ${text(created.payload, "title") ?? titles.get(id) ?? "a change"}`,
      detail: text(created.payload, "kind")?.replaceAll("_", " ") ?? null,
      links: id
        ? [{ target: { kind: "proposal", id }, label: "Open the proposal" }]
        : [],
    })
  }
  for (const decided of events.filter((e) => e.kind === "proposal.decided")) {
    const id = text(decided.payload, "proposal_id") ?? ""
    steps.push({
      at: at(decided),
      tone: "you",
      title: `You ${text(decided.payload, "verdict") ?? "decided"} "${titles.get(id) ?? "a proposal"}"`,
      detail: text(decided.payload, "note"),
      links: [],
    })
  }

  const byId = new Map([...events, ...later].map((e) => [e.id, e]))
  const published = [...byId.values()]
    .filter(
      (e) =>
        e.kind === "kb.published" && e.work_item_id === events[0].work_item_id
    )
    .sort((a, b) => a.id - b.id)
  for (const event of published) {
    const doc = text(event.payload, "doc_id") ?? "an article"
    const version = event.payload?.version
    steps.push({
      at: at(event),
      tone: "published",
      title: `Published ${doc} v${String(version ?? "?")} to the knowledge base`,
      detail: `In effect from ${text(event.payload, "effective_date") ?? "now"}.`,
      links: [],
    })
    const prefix = `${doc}@v${String(version ?? "")}`
    const citing = later.filter(
      (e) =>
        e.kind === "ticket.replied" &&
        e.id > event.id &&
        list(e.payload, "citations").some(
          (c) => typeof c === "string" && c.startsWith(prefix)
        )
    )
    if (citing.length > 0) {
      steps.push({
        at: at(citing[0]),
        tone: "cited",
        title: `Support cited it in ${citing.length} repl${citing.length === 1 ? "y" : "ies"} afterwards`,
        detail: text(citing[0].payload, "reply"),
        links: citing.slice(0, 5).flatMap((e) =>
          e.work_item_id
            ? [
                {
                  href: `/runs/${e.work_item_id}`,
                  label: text(e.payload, "ticket_id") ?? e.work_item_id,
                },
              ]
            : []
        ),
      })
    }
  }
  return steps.sort((a, b) => a.at - b.at)
}

import type { AhqEvent, Lineup } from "@/lib/api/types"

import type { Polyline } from "./geometry"
import {
  type AgentNode,
  isAgent,
  type NodeId,
  route,
  type StoreId,
} from "./layout"
import { modelRail, type ModelRow, RETRIEVAL_ROW } from "./models"
import { flag, list, num, record, text } from "./payload"
import { versionsIn } from "@/lib/format"

export const MOVE_MS = 700
const MIN_BEAM_MS = 450
const MIN_PACKET_MS = 900
const LINGER_MS = 2500

export type Tone = "ticket" | "alert" | "flag" | "attack" | "proposal"

export type Stop = { node: NodeId; at: number }

export type Item = {
  id: string
  workItemId: string | null
  kind: Tone
  stops: Stop[]
  tones: { at: number; tone: Tone }[]
  waits: { start: number; end: number | null }[]
  endAt: number | null
  title: string
}

export type Beam = {
  node: NodeId
  row: string
  start: number
  end: number
  cost: number
  seconds: number
}

export type PacketStatus = "ok" | "refused" | "waiting" | "cached" | "failed"

export type Packet = {
  node: NodeId
  store: StoreId
  start: number
  end: number
  status: PacketStatus
  label: string
}

export type Flash = {
  node: NodeId
  start: number
  end: number
  tone: "red" | "amber"
}

export type Particle = {
  path: Polyline
  start: number
  duration: number
  kind: "reply" | "message" | "background" | "review"
}

export type Caption = {
  at: number
  text: string
  chapter?: string
  workItemId?: string | null
}

export type Count = { at: number; key: string; delta: number }

export type Wire = {
  key: string
  kind: "model" | "tool"
  node: NodeId
  to: string
}

export type SimAnchor = {
  wall: number
  sim: number
  halt?: boolean
  pace?: number
}

function paceIn(payload: Record<string, unknown> = {}): number | undefined {
  const minutes = Number(payload.tick_minutes)
  const seconds = Number(payload.tick_seconds)
  return minutes > 0 && seconds > 0 ? (minutes * 60) / seconds : undefined
}

export type Timeline = {
  origin: number
  duration: number
  items: Item[]
  beams: Beam[]
  packets: Packet[]
  flashes: Flash[]
  particles: Particle[]
  captions: Caption[]
  chapters: { at: number; label: string }[]
  counts: Count[]
  wires: Wire[]
  rows: ModelRow[]
  sim: SimAnchor[]
}

const NODE_OF_ACTOR: Record<string, NodeId> = {
  guard: "screen",
  dispatcher: "dispatcher",
  support: "support",
  ops: "ops",
  insights: "insights",
  customer: "customers",
  qa: "qa",
}

const AGENT_NAMES: Record<string, string> = {
  support: "Support",
  ops: "Ops",
  insights: "Insights",
  dispatcher: "The Dispatcher",
  human: "a person",
}

const SOURCE: Record<string, NodeId> = {
  ticket: "customers",
  alert: "store",
  flag: "support",
}

export function storeOf(tool: string): StoreId | null {
  if (tool.startsWith("knowledge_")) {
    return "knowledge"
  }
  if (tool.startsWith("analytics_")) {
    return "analytics"
  }
  if (tool === "flag_pattern" || tool === "transfer_to_human_agents") {
    return null
  }
  return "orders"
}

export function wallTimes(events: readonly AhqEvent[]): number[] {
  const raw = events.map((event) => {
    if (event.recorded_at) {
      return Date.parse(event.recorded_at)
    }
    const simulated = event.actor === "simulator" || event.actor === "monitor"
    return simulated ? Number.NaN : Date.parse(event.occurred_at)
  })
  const known = raw.find((time) => !Number.isNaN(time)) ?? 0
  let previous = known
  return raw.map((time) => {
    previous = Number.isNaN(time) ? previous : time
    return previous
  })
}

export function buildTimeline(
  events: readonly AhqEvent[],
  lineup: Lineup | null | undefined
): Timeline {
  const rail = modelRail(lineup)
  const ordered = [...events].sort((a, b) => a.id - b.id)
  const times = wallTimes(ordered)
  const origin = times.length > 0 ? Math.min(...times) : 0

  const items = new Map<string, Item>()
  const beams: Beam[] = []
  const packets: Packet[] = []
  const flashes: Flash[] = []
  const particles: Particle[] = []
  const captions: Caption[] = []
  const chapters: { at: number; label: string }[] = []
  const counts: Count[] = []
  const wires = new Map<string, Wire>()
  const sim: SimAnchor[] = []

  const chapter = (at: number, label: string) => {
    if (!chapters.some((existing) => existing.label === label)) {
      chapters.push({ at, label })
    }
  }
  const say = (
    at: number,
    words: string,
    workItemId: string | null = null,
    mark?: string
  ) => {
    captions.push({ at, text: words, workItemId, chapter: mark })
    if (mark) {
      chapter(at, mark)
    }
  }
  const bump = (at: number, key: string, delta = 1) =>
    counts.push({ at, key, delta })
  const wire = (kind: Wire["kind"], node: NodeId, to: string) => {
    const key = `${node}>${to}`
    if (!wires.has(key)) {
      wires.set(key, { key, kind, node, to })
    }
  }
  const beam = (
    node: NodeId,
    row: string,
    start: number,
    end: number,
    cost = 0,
    seconds = 0
  ) => {
    wire("model", node, row)
    beams.push({
      node,
      row,
      start,
      end: Math.max(end, start + MIN_BEAM_MS),
      cost,
      seconds,
    })
  }
  const stopAt = (item: Item, node: NodeId, at: number) => {
    const last = item.stops[item.stops.length - 1]
    if (last?.node === node) {
      return
    }
    item.stops.push({ node, at: last ? Math.max(at, last.at + 1) : at })
  }
  const toneAt = (item: Item, tone: Tone, at: number) =>
    item.tones.push({ at, tone })
  const current = (item: Item): NodeId => item.stops[item.stops.length - 1].node
  const lastAgent = (item: Item): AgentNode | null => {
    for (let i = item.stops.length - 1; i >= 0; i--) {
      const node = item.stops[i].node
      if (isAgent(node)) {
        return node
      }
    }
    return null
  }
  const pastTriage = (item: Item) =>
    item.stops.some((stop) => isAgent(stop.node) || stop.node === "you")
  const pseudo = (
    id: string,
    kind: Tone,
    node: NodeId,
    at: number,
    title: string
  ): Item => {
    const item: Item = {
      id,
      workItemId: null,
      kind,
      stops: [{ node, at }],
      tones: [{ at, tone: kind }],
      waits: [],
      endAt: null,
      title,
    }
    items.set(id, item)
    return item
  }

  const adopt = (
    workId: string,
    event: AhqEvent,
    at: number
  ): Item | undefined => {
    const node = event.actor ? NODE_OF_ACTOR[event.actor] : undefined
    const where: NodeId | undefined =
      event.kind === "work.routed"
        ? "dispatcher"
        : event.kind === "approval.requested"
          ? "you"
          : node && node !== "customers" && node !== "qa"
            ? node
            : undefined
    if (!where || event.kind === "work.created") {
      return undefined
    }
    const kind: Tone =
      where === "ops" || where === "insights" ? "alert" : "ticket"
    const item: Item = {
      id: workId,
      workItemId: workId,
      kind,
      stops: [{ node: where, at }],
      tones: [{ at, tone: kind }],
      waits: [],
      endAt: null,
      title: kind,
    }
    items.set(workId, item)
    return item
  }

  ordered.forEach((event, index) => {
    const at = times[index] - origin
    const payload = event.payload
    const workId = event.work_item_id ?? null
    const item = workId
      ? (items.get(workId) ?? adopt(workId, event, at))
      : undefined
    const actorNode = event.actor ? NODE_OF_ACTOR[event.actor] : undefined
    switch (event.kind) {
      case "sim.started":
        sim.push({
          wall: at,
          sim: Date.parse(event.occurred_at),
          pace: paceIn(payload),
        })
        say(
          at,
          "The simulated day starts: customers write in and parcels move.",
          null,
          "Day starts"
        )
        break
      case "sim.paused":
      case "sim.stopped":
        sim.push({ wall: at, sim: Date.parse(event.occurred_at), halt: true })
        break
      case "sim.resumed":
        sim.push({
          wall: at,
          sim: Date.parse(event.occurred_at),
          pace: paceIn(payload),
        })
        break
      case "sim.finished":
        sim.push({ wall: at, sim: Date.parse(event.occurred_at), halt: true })
        say(
          at,
          "The simulated day ends; the team finishes what it started.",
          null,
          "Day ends"
        )
        break
      case "ticket.opened": {
        sim.push({ wall: at, sim: Date.parse(event.occurred_at) })
        bump(at, "customers.tickets")
        if (flag(payload, "for_agents")) {
          bump(at, "customers.agents")
        } else {
          const x = 470 + ((event.id * 37) % 180)
          particles.push({
            path: [
              [x, 50],
              [x, 22],
            ],
            start: at,
            duration: 1300,
            kind: "background",
          })
        }
        break
      }
      case "order.shipped":
        sim.push({ wall: at, sim: Date.parse(event.occurred_at) })
        bump(at, "store.shipped")
        break
      case "parcel.delivered":
        sim.push({ wall: at, sim: Date.parse(event.occurred_at) })
        bump(at, "store.delivered")
        if (flag(payload, "late")) {
          bump(at, "store.late")
        }
        break
      case "kpi.alert": {
        sim.push({ wall: at, sim: Date.parse(event.occurred_at) })
        bump(at, "store.alerts")
        flashes.push({
          node: "store",
          start: at,
          end: at + 1200,
          tone: "amber",
        })
        const segment = record(payload, "segment")
        const where = segment
          ? Object.values(segment)
              .filter((v) => typeof v === "string")
              .join(" in the ")
          : "a segment"
        say(
          at,
          `The hourly delivery check raised an alert: ${where}.`,
          null,
          "Alert"
        )
        break
      }
      case "work.created": {
        const kind = text(payload, "kind") ?? "ticket"
        const source = SOURCE[kind]
        if (!workId || !source) {
          break
        }
        items.set(workId, {
          id: workId,
          workItemId: workId,
          kind: kind as Tone,
          stops: [{ node: source, at }],
          tones: [{ at, tone: kind as Tone }],
          waits: [],
          endAt: null,
          title: kind,
        })
        break
      }
      case "model.called": {
        if (!actorNode) {
          break
        }
        const seconds = num(payload, "seconds") ?? 0
        const start = at - seconds * 1000
        beam(
          actorNode,
          rail.rowOf(event.actor ?? ""),
          start,
          at,
          num(payload, "cost_usd") ?? 0,
          seconds
        )
        if (event.actor === "guard") {
          bump(at, "screen.checked")
        }
        if (!item) {
          break
        }
        if (event.actor === "guard") {
          if (!pastTriage(item)) {
            stopAt(item, "screen", start)
          }
        } else if (event.actor === "dispatcher") {
          stopAt(item, "dispatcher", start)
        } else if (isAgent(actorNode) && current(item) !== actorNode) {
          stopAt(item, actorNode, start)
        }
        break
      }
      case "work.routed": {
        bump(at, "dispatcher.routed")
        const to = text(payload, "route")
        if (item && to) {
          stopAt(item, to === "human" ? "you" : (to as NodeId), at)
        }
        break
      }
      case "tool.called": {
        if (!actorNode) {
          break
        }
        const tool = text(payload, "tool") ?? "tool"
        const seconds = num(payload, "seconds") ?? 0
        const start = at - seconds * 1000
        const end = start + Math.max(seconds * 1000, MIN_PACKET_MS)
        const verdict = text(payload, "verdict")
        const cached = flag(payload, "cached") === true
        const ok = flag(payload, "ok") !== false
        const store = cached ? "cache" : storeOf(tool)
        if (item && isAgent(actorNode) && current(item) !== actorNode) {
          stopAt(item, actorNode, start)
        }
        if (store === null) {
          break
        }
        const status: PacketStatus =
          verdict === "refused"
            ? "refused"
            : cached
              ? "cached"
              : ok
                ? "ok"
                : "failed"
        wire("tool", actorNode, store)
        packets.push({
          node: actorNode,
          store,
          start,
          end,
          status,
          label: toolLabel(tool, status, payload),
        })
        bump(end, `${store}.calls`)
        if (status === "refused") {
          bump(end, `${store}.refused`)
          flashes.push({
            node: actorNode,
            start,
            end: start + 900,
            tone: "red",
          })
          say(
            start,
            `The permission check refused ${tool}: ${clip(text(payload, "reason") ?? "not allowed", 90)}`,
            workId
          )
        }
        if (tool === "knowledge_search" && !cached) {
          beam(actorNode, RETRIEVAL_ROW, start, end)
        }
        break
      }
      case "approval.requested": {
        const node = item ? lastAgent(item) : null
        if (node) {
          flashes.push({ node, start: at, end: at + 1200, tone: "amber" })
        }
        if (item) {
          stopAt(item, "you", at)
          item.waits.push({ start: at, end: null })
        }
        const action = text(payload, "action") ?? "an action"
        say(
          at,
          `${action} waits for your approval: ${clip(text(payload, "reason") ?? "", 100)}`,
          workId,
          "Waits for you"
        )
        break
      }
      case "approval.decided": {
        bump(at, "you.decided")
        const verdict = text(payload, "verdict") ?? "decided"
        if (item) {
          const open = item.waits.find((wait) => wait.end === null)
          if (open) {
            open.end = at
          }
          const back = lastAgent(item)
          if (back) {
            stopAt(item, back, at)
          }
        }
        say(
          at,
          `You ${verdict === "reject" ? "rejected" : verdict === "edit" ? "edited and approved" : "approved"} it.`,
          workId
        )
        break
      }
      case "agent.handoff": {
        const to = text(payload, "to")
        const from = text(payload, "from") ?? event.actor ?? ""
        if (item && to) {
          stopAt(item, to === "human" ? "you" : (to as NodeId), at)
        }
        if (to && to !== "human") {
          say(
            at,
            `${AGENT_NAMES[from] ?? from} handed the work to ${AGENT_NAMES[to] ?? to}.`,
            workId
          )
        }
        break
      }
      case "guardrail.blocked": {
        const stage = text(payload, "stage")
        const node: NodeId = stage === "output" ? "support" : "screen"
        flashes.push({ node, start: at, end: at + 1400, tone: "red" })
        if (item) {
          toneAt(item, "attack", at)
        }
        if (stage === "output") {
          bump(at, "support.held")
          say(
            at,
            "The reply check held back a reply that named another customer.",
            workId
          )
        } else {
          bump(at, "screen.blocked")
          const threat = text(payload, "threat") ?? "a threat"
          const by =
            text(payload, "by") === "pattern"
              ? "on its patterns"
              : "with its classifier"
          say(
            at,
            `The input check held a message ${by} (${threat.replace("_", " ")}).`,
            workId,
            "Attack held"
          )
        }
        break
      }
      case "ticket.message":
        if (item && event.actor === "customer") {
          const owner = lastAgent(item) ?? "support"
          particles.push({
            path: route("customers", owner),
            start: at,
            duration: 1400,
            kind: "message",
          })
        }
        break
      case "ticket.replied": {
        particles.push({
          path: route("support", "customers"),
          start: at,
          duration: 1100,
          kind: "reply",
        })
        if (text(payload, "status") === "resolved") {
          bump(at, "support.resolved")
          say(
            at,
            `Support resolved a ticket: ${clip(text(payload, "summary") ?? "", 110)}`,
            workId
          )
        }
        break
      }
      case "work.completed":
      case "work.cancelled":
      case "work.failed":
      case "ticket.closed":
        if (item && item.endAt === null) {
          item.endAt = at
        }
        break
      case "work.escalated":
        if (item) {
          stopAt(item, "you", at)
          item.endAt = at + LINGER_MS
          bump(at, "you.escalated")
        }
        break
      case "incident.filed":
        bump(at, "ops.incidents")
        flashes.push({ node: "ops", start: at, end: at + 1500, tone: "amber" })
        say(
          at,
          `Ops filed an incident: ${clip(text(payload, "title") ?? "", 110)}`,
          workId,
          "Incident"
        )
        break
      case "proposal.created": {
        bump(at, "insights.proposals")
        const id = `proposal:${text(payload, "proposal_id") ?? event.id}`
        const proposal = pseudo(
          id,
          "proposal",
          "insights",
          at,
          text(payload, "title") ?? "proposal"
        )
        stopAt(proposal, "you", at + MOVE_MS)
        proposal.waits.push({ start: at + MOVE_MS, end: null })
        say(
          at,
          `Insights proposed: ${clip(text(payload, "title") ?? "", 110)}`,
          workId
        )
        break
      }
      case "proposal.decided": {
        bump(at, "you.decided")
        const proposal = items.get(
          `proposal:${text(payload, "proposal_id") ?? ""}`
        )
        if (proposal) {
          const open = proposal.waits.find((wait) => wait.end === null)
          if (open) {
            open.end = at
          }
          proposal.endAt = at + 600
        }
        say(
          at,
          `You ${text(payload, "verdict") === "rejected" ? "rejected" : "approved"} a proposal.`,
          workId
        )
        break
      }
      case "kb.published": {
        wire("tool", "you", "knowledge")
        packets.push({
          node: "you",
          store: "knowledge",
          start: at,
          end: at + 1400,
          status: "ok",
          label: `published ${text(payload, "doc_id") ?? "an article"}`,
        })
        beam("you", RETRIEVAL_ROW, at, at + 1000)
        bump(at, "knowledge.published")
        say(
          at,
          `Published ${text(payload, "doc_id") ?? "an article"} v${num(payload, "version") ?? "?"} to the knowledge base.`,
          workId,
          "Published"
        )
        break
      }
      case "qa.reviewed": {
        bump(at, "qa.reviewed")
        const seconds = num(payload, "seconds") ?? 1
        const agent = text(payload, "agent") ?? "support"
        const from: NodeId =
          agent === "dispatcher"
            ? "dispatcher"
            : isAgent(agent)
              ? agent
              : "support"
        particles.push({
          path: route(from, "qa"),
          start: at - seconds * 1000 - 800,
          duration: 800,
          kind: "review",
        })
        beam(
          "qa",
          rail.rowOf("qa"),
          at - seconds * 1000,
          at,
          num(payload, "cost_usd") ?? 0,
          seconds
        )
        const verdicts = record(payload, "verdicts")
        const failed = verdicts
          ? Object.values(verdicts).filter((v) => v === "fail").length
          : 0
        if (failed > 0) {
          say(
            at,
            `The QA reviewer failed ${failed} criteria on a ${AGENT_NAMES[agent] ?? agent} run.`,
            workId
          )
        }
        break
      }
      case "pattern.flagged":
        say(
          at,
          `Support flagged a pattern for the team: ${clip(text(payload, "summary") ?? text(payload, "topic") ?? "", 100)}`,
          workId
        )
        break
      case "work.deferred":
        say(
          at,
          `A provider was busy; the work waits ${Math.round(num(payload, "after_seconds") ?? 0)} s and resumes.`,
          workId
        )
        break
      case "breaker.opened":
        say(
          at,
          `A model's breaker opened; calls fall back to ${text(payload, "fallback") ?? "another model"}.`
        )
        break
      case "agent.paused":
        say(
          at,
          `${AGENT_NAMES[event.actor ?? ""] ?? "An agent"} is paused; its work goes to a person.`
        )
        break
      case "version.rolled_back":
        say(
          at,
          `A canary was rolled back: ${versionsIn(text(payload, "version_id") ?? "a version")}.`,
          null,
          "Rollback"
        )
        break
      default:
        break
    }
  })

  const all = [...items.values()]
  const last = times.length > 0 ? Math.max(...times) - origin : 0
  const ends = [
    last,
    ...beams.map((b) => b.end),
    ...packets.map((p) => p.end),
    ...all.map((i) => i.endAt ?? 0),
  ]
  return {
    origin,
    duration: Math.max(...ends) + 2000,
    items: all,
    beams,
    packets,
    flashes,
    particles,
    captions: captions.sort((a, b) => a.at - b.at),
    chapters: chapters.sort((a, b) => a.at - b.at),
    counts: counts.sort((a, b) => a.at - b.at),
    wires: [...wires.values()],
    rows: rail.rows,
    sim: sim.sort((a, b) => a.wall - b.wall),
  }
}

function toolLabel(
  tool: string,
  status: PacketStatus,
  payload: AhqEvent["payload"]
): string {
  if (status === "refused") {
    return `${tool} · refused`
  }
  if (status === "cached") {
    return `${tool} · read cache`
  }
  if (status === "failed") {
    return `${tool} · error`
  }
  const result = record(payload, "result")
  const seconds = num(payload, "seconds")
  const passages = list(result ?? {}, "passages")
  const detail =
    passages.length > 0
      ? `${passages.length} passages`
      : typeof result?.rows === "number"
        ? `${result.rows} rows`
        : typeof result?.status === "string"
          ? result.status
          : seconds !== null
            ? `${seconds.toFixed(2)} s`
            : ""
  return detail ? `${tool} · ${detail}` : tool
}

function clip(value: string, limit: number): string {
  const flat = value.replace(/\s+/g, " ").trim()
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 3)}...`
}

export function nextActivity(timeline: Timeline, t: number): number | null {
  let next = Number.POSITIVE_INFINITY
  let active = false
  const consider = (start: number, end: number) => {
    if (start <= t && t < end) {
      active = true
    } else if (start > t) {
      next = Math.min(next, start)
    }
  }
  for (const beam of timeline.beams) {
    consider(beam.start, beam.end)
  }
  for (const packet of timeline.packets) {
    consider(packet.start, packet.end)
  }
  for (const particle of timeline.particles) {
    if (particle.kind !== "background") {
      consider(particle.start, particle.start + particle.duration)
    }
  }
  for (const item of timeline.items) {
    for (const stop of item.stops) {
      consider(stop.at - MOVE_MS, stop.at)
    }
  }
  if (active) {
    return null
  }
  return Number.isFinite(next) ? next : timeline.duration
}

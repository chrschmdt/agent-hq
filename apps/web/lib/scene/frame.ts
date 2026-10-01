import { clock } from "@/lib/format"

import {
  type Curve,
  ease,
  type Point,
  pointOnCurve,
  pointOnPolyline,
  wireBetween,
} from "./geometry"
import {
  MODEL_ANCHOR,
  modelRow,
  type NodeId,
  PARK,
  route,
  rowEdge,
  STORES,
  type StoreId,
  TAG_AT,
  TOOL_ANCHOR,
} from "./layout"
import {
  MOVE_MS,
  type Caption,
  type PacketStatus,
  type SimAnchor,
  type Timeline,
  type Tone,
} from "./timeline"

const FADE_MS = 900
const PACE_WINDOW_MS = 30_000
const PACE_MIN_MS = 4_000
const PARK_SPREAD = 17

export type NodeTone = "idle" | "live" | "amber" | "red"
export type WireState = "idle" | "model" | "tool" | "refused"

export type Dot = {
  key: string
  x: number
  y: number
  size: number
  tone: Tone | "reply" | "message" | "background" | "review"
  opacity: number
  waiting: boolean
  workItemId: string | null
}

export type Packet = { key: string; x: number; y: number; status: PacketStatus }
export type Spark = { key: string; x: number; y: number }
export type Tag = {
  key: string
  x: number
  y: number
  text: string
  status: PacketStatus
}

export type NodeView = {
  tone: NodeTone
  busy: boolean
  stat: string
  cost: string | null
}
export type RowView = {
  id: string
  title: string
  provider: string
  roles: string
  reasoning: boolean
  live: number
  stat: string
}
export type StoreView = { live: boolean; stat: string }

export type Frame = {
  t: number
  dots: Dot[]
  packets: Packet[]
  sparks: Spark[]
  tags: Tag[]
  wires: { key: string; path: Curve; state: WireState }[]
  nodes: Record<NodeId, NodeView>
  rows: RowView[]
  stores: Record<StoreId, StoreView>
  caption: Caption | null
  clock: string | null
  totals: { modelCalls: number; toolCalls: number; spent: number }
}

export function wirePath(
  timeline: Timeline,
  node: NodeId,
  to: string
): Curve | null {
  const store = STORES[to as StoreId]
  if (store) {
    const from = TOOL_ANCHOR[node]
    return from ? wireBetween(from, rowEdge(store, "right")) : null
  }
  const index = timeline.rows.findIndex((row) => row.id === to)
  const from = MODEL_ANCHOR[node]
  return from && index >= 0
    ? wireBetween(from, rowEdge(modelRow(index), "left"))
    : null
}

export function simulatedAt(
  timeline: Timeline,
  t: number,
  leadMs = 0
): number | null {
  const anchors = timeline.sim
  if (anchors.length === 0 || t < anchors[0].wall) {
    return null
  }
  let i = anchors.length - 1
  while (i > 0 && anchors[i].wall > t) {
    i--
  }
  const a = anchors[i]
  const b = anchors[i + 1]
  if (a.halt || (b && b.wall === a.wall)) {
    return a.sim
  }
  if (!b) {
    return a.sim + paceOf(anchors) * Math.min(t - a.wall, leadMs)
  }
  return a.sim + ((t - a.wall) / (b.wall - a.wall)) * (b.sim - a.sim)
}

function paceOf(anchors: readonly SimAnchor[]): number {
  const last = anchors[anchors.length - 1]
  let first = anchors.length - 1
  while (first > 0) {
    const before = anchors[first - 1]
    if (
      before.halt ||
      before.sim > anchors[first].sim ||
      last.wall - before.wall > PACE_WINDOW_MS
    ) {
      break
    }
    first--
  }
  const span = last.wall - anchors[first].wall
  return span >= PACE_MIN_MS
    ? Math.max(0, (last.sim - anchors[first].sim) / span)
    : (anchors[first].pace ?? 0)
}

const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`

const within = (t: number, start: number, end: number) => t >= start && t < end

export function frameAt(timeline: Timeline, t: number): Frame {
  const tones = new Map<string, NodeTone>()
  const light = (key: string, tone: NodeTone) => {
    const now = tones.get(key)
    if (now === "red" || (now === "amber" && tone === "live")) {
      return
    }
    tones.set(key, tone)
  }

  const counts = new Map<string, number>()
  for (const step of timeline.counts) {
    if (step.at > t) {
      break
    }
    counts.set(step.key, (counts.get(step.key) ?? 0) + step.delta)
  }
  const count = (key: string) => counts.get(key) ?? 0

  const wireStates = new Map<string, WireState>()
  const rowLive = new Map<string, number>()
  const rowDone = new Map<string, { calls: number; seconds: number }>()
  const cost = new Map<string, number>()
  const sparks: Spark[] = []
  let modelCalls = 0
  let spent = 0
  timeline.beams.forEach((beam, index) => {
    if (beam.end <= t) {
      modelCalls += 1
      spent += beam.cost
      cost.set(beam.node, (cost.get(beam.node) ?? 0) + beam.cost)
      const done = rowDone.get(beam.row) ?? { calls: 0, seconds: 0 }
      rowDone.set(beam.row, {
        calls: done.calls + 1,
        seconds: done.seconds + beam.seconds,
      })
      return
    }
    if (!within(t, beam.start, beam.end)) {
      return
    }
    const key = `${beam.node}>${beam.row}`
    wireStates.set(key, "model")
    rowLive.set(beam.row, (rowLive.get(beam.row) ?? 0) + 1)
    light(beam.node, "live")
    const path = wirePath(timeline, beam.node, beam.row)
    const f = (t - beam.start) / (beam.end - beam.start)
    const g = f < 0.2 ? f / 0.2 : f > 0.8 ? (1 - f) / 0.2 : null
    if (path && g !== null) {
      const [x, y] = pointOnCurve(path, g)
      sparks.push({ key: `s${index}`, x, y })
    }
  })

  const packets: Packet[] = []
  const tags: Tag[] = []
  const storeLive = new Set<string>()
  let toolCalls = 0
  timeline.packets.forEach((packet, index) => {
    if (packet.end <= t) {
      toolCalls += 1
      return
    }
    if (!within(t, packet.start, packet.end)) {
      return
    }
    const key = `${packet.node}>${packet.store}`
    const refused = packet.status === "refused" || packet.status === "failed"
    wireStates.set(key, refused ? "refused" : "tool")
    light(packet.node, refused ? "red" : "live")
    const path = wirePath(timeline, packet.node, packet.store)
    const f = (t - packet.start) / (packet.end - packet.start)
    const reach =
      packet.status === "refused" || packet.status === "waiting" ? 0.22 : 1
    const g = (f < 0.45 ? f / 0.45 : f < 0.55 ? 1 : (1 - f) / 0.45) * reach
    if (path) {
      const [x, y] = pointOnCurve(path, g)
      packets.push({ key: `p${index}`, x, y, status: packet.status })
    }
    if (!refused && f > 0.3 && f < 0.7) {
      storeLive.add(packet.store)
    }
    const at = TAG_AT[packet.node]
    if (at && !tags.some((tag) => tag.x === at[0])) {
      tags.push({
        key: `t${index}`,
        x: at[0],
        y: at[1],
        text: packet.label,
        status: packet.status,
      })
    }
  })

  for (const flash of timeline.flashes) {
    if (within(t, flash.start, flash.end)) {
      light(flash.node, flash.tone)
    }
  }

  const dots: Dot[] = []
  const parked = new Map<NodeId, Dot[]>()
  const open = new Map<NodeId, number>()
  for (const item of timeline.items) {
    const first = item.stops[0]
    if (!first || t < first.at) {
      continue
    }
    if (item.endAt !== null && t > item.endAt + FADE_MS) {
      continue
    }
    let i = item.stops.length - 1
    while (i > 0 && item.stops[i].at > t) {
      i--
    }
    const here = item.stops[i]
    const next = item.stops[i + 1]
    let point: Point = PARK[here.node]
    let node: NodeId | null = here.node
    if (next) {
      const leave = Math.max(here.at, next.at - MOVE_MS)
      if (t >= leave) {
        point = pointOnPolyline(
          route(here.node, next.node),
          ease((t - leave) / Math.max(1, next.at - leave))
        )
        node = null
      }
    }
    let tone: Tone = item.kind
    for (const change of item.tones) {
      if (change.at <= t) {
        tone = change.tone
      }
    }
    const waiting = item.waits.some(
      (wait) => t >= wait.start && (wait.end === null || t < wait.end)
    )
    const opacity =
      item.endAt !== null && t > item.endAt
        ? Math.max(0, 1 - (t - item.endAt) / FADE_MS)
        : 1
    const dot: Dot = {
      key: item.id,
      x: point[0],
      y: point[1],
      size: item.kind === "proposal" ? 10 : 13,
      tone,
      opacity,
      waiting,
      workItemId: item.workItemId,
    }
    dots.push(dot)
    if (node !== null) {
      parked.set(node, [...(parked.get(node) ?? []), dot])
      if (item.endAt === null || t <= item.endAt) {
        open.set(node, (open.get(node) ?? 0) + 1)
      }
    }
  }
  for (const group of parked.values()) {
    group.forEach((dot, index) => {
      dot.x += (index - (group.length - 1) / 2) * PARK_SPREAD
    })
  }
  timeline.particles.forEach((particle, index) => {
    if (!within(t, particle.start, particle.start + particle.duration)) {
      return
    }
    const f = (t - particle.start) / particle.duration
    const [x, y] = pointOnPolyline(
      particle.path,
      particle.kind === "background" ? f : ease(f)
    )
    dots.push({
      key: `m${index}`,
      x,
      y,
      size: particle.kind === "background" ? 6 : 8,
      tone: particle.kind,
      opacity: particle.kind === "background" ? 0.7 * (1 - f) : 1,
      waiting: false,
      workItemId: null,
    })
  })

  const money = (node: NodeId) => `$${(cost.get(node) ?? 0).toFixed(3)}`
  const view = (node: NodeId, stat: string, spends = false): NodeView => ({
    tone: tones.get(node) ?? "idle",
    busy: (open.get(node) ?? 0) > 0,
    stat,
    cost: spends ? money(node) : null,
  })
  const alerts = count("store.alerts")
  const nodes: Record<NodeId, NodeView> = {
    customers: view(
      "customers",
      `${count("customers.tickets")} today · ${count("customers.agents")} to the agents`
    ),
    store: view(
      "store",
      alerts
        ? `${alerts} alert${alerts === 1 ? "" : "s"} · ${count("store.delivered")} delivered`
        : `${count("store.shipped")} shipped · ${count("store.delivered")} delivered`
    ),
    screen: view(
      "screen",
      `checked ${count("screen.checked")} · held ${count("screen.blocked")}`,
      true
    ),
    dispatcher: view(
      "dispatcher",
      `routed ${count("dispatcher.routed")}`,
      true
    ),
    support: view(
      "support",
      `${open.get("support") ?? 0} open · ${count("support.resolved")} resolved`,
      true
    ),
    ops: view(
      "ops",
      `${open.get("ops") ?? 0} open · ${plural(count("ops.incidents"), "incident")}`,
      true
    ),
    insights: view(
      "insights",
      `${open.get("insights") ?? 0} open · ${plural(count("insights.proposals"), "proposal")}`,
      true
    ),
    you: view(
      "you",
      `${open.get("you") ?? 0} waiting · ${count("you.decided")} decided`
    ),
    qa: view("qa", `${count("qa.reviewed")} reviewed`, true),
  }

  const rows: RowView[] = timeline.rows.map((row) => {
    const live = rowLive.get(row.id) ?? 0
    const done = rowDone.get(row.id) ?? { calls: 0, seconds: 0 }
    const average =
      done.calls > 0 ? ` · ${(done.seconds / done.calls).toFixed(1)} s avg` : ""
    return {
      id: row.id,
      title: row.title,
      provider: row.provider,
      roles: row.roles.join(", ") + (row.reasoning ? ", with reasoning" : ""),
      reasoning: row.reasoning,
      live,
      stat: `${live ? `${live} live · ` : ""}${done.calls} calls${average}`,
    }
  })

  const refused = count("orders.refused")
  const hits = count("cache.calls")
  const stores: Record<StoreId, StoreView> = {
    orders: {
      live: storeLive.has("orders"),
      stat: `${count("orders.calls")} calls${refused ? ` · ${refused} refused` : ""}`,
    },
    knowledge: {
      live: storeLive.has("knowledge"),
      stat: `${count("knowledge.calls")} searches${count("knowledge.published") ? ` · ${count("knowledge.published")} published` : ""}`,
    },
    analytics: {
      live: storeLive.has("analytics"),
      stat: `${count("analytics.calls")} queries`,
    },
    cache: {
      live: storeLive.has("cache"),
      stat: `${hits} hit${hits === 1 ? "" : "s"}`,
    },
  }

  let caption: Caption | null = null
  for (const candidate of timeline.captions) {
    if (candidate.at > t) {
      break
    }
    caption = candidate
  }

  const wires = timeline.wires.flatMap((wire) => {
    const path = wirePath(timeline, wire.node, wire.to)
    return path
      ? [
          {
            key: wire.key,
            path,
            state: wireStates.get(wire.key) ?? ("idle" as WireState),
          },
        ]
      : []
  })

  const simulated = simulatedAt(timeline, t)
  return {
    t,
    dots,
    packets,
    sparks,
    tags,
    wires,
    nodes,
    rows,
    stores,
    caption,
    clock: simulated === null ? null : clock(new Date(simulated).toISOString()),
    totals: { modelCalls, toolCalls, spent },
  }
}

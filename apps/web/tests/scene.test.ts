import { describe, expect, it } from "vitest"

import type { AhqEvent, Lineup } from "@/lib/api/types"
import { frameAt, simulatedAt } from "@/lib/scene/frame"
import { modelRail } from "@/lib/scene/models"
import {
  buildTimeline,
  nextActivity,
  storeOf,
  type Timeline,
  wallTimes,
} from "@/lib/scene/timeline"

const T0 = Date.parse("2026-09-28T15:00:00Z")
const SIM = "2026-06-15T12:00:00Z"
let nextId = 1

function event(
  kind: AhqEvent["kind"],
  seconds: number,
  fields: Partial<AhqEvent> = {}
): AhqEvent {
  return {
    id: nextId++,
    kind,
    occurred_at: new Date(T0 + seconds * 1000).toISOString(),
    recorded_at: new Date(T0 + seconds * 1000).toISOString(),
    actor: null,
    work_item_id: null,
    payload: {},
    ...fields,
  }
}

const work = (
  kind: AhqEvent["kind"],
  seconds: number,
  actor: string,
  payload: Record<string, unknown> = {}
) => event(kind, seconds, { actor, work_item_id: "wi_1", payload })

const DEMO: Lineup = {
  profile: "demo",
  roles: {
    guard: {
      key: "claude-haiku-4-5",
      id: "anthropic/claude-haiku-4.5",
      provider: "anthropic",
      reasoning: false,
    },
    dispatcher: {
      key: "claude-haiku-4-5",
      id: "anthropic/claude-haiku-4.5",
      provider: "anthropic",
      reasoning: false,
    },
    support: {
      key: "claude-sonnet-5",
      id: "anthropic/claude-sonnet-5",
      provider: "anthropic",
      reasoning: true,
    },
    ops: {
      key: "claude-sonnet-5",
      id: "anthropic/claude-sonnet-5",
      provider: "anthropic",
      reasoning: true,
    },
    insights: {
      key: "claude-sonnet-5",
      id: "anthropic/claude-sonnet-5",
      provider: "anthropic",
      reasoning: true,
    },
    customer: {
      key: "gpt-6-luna",
      id: "openai/gpt-6-luna",
      provider: "openai",
      reasoning: false,
    },
    qa: {
      key: "gpt-6-sol",
      id: "openai/gpt-6-sol",
      provider: "openai",
      reasoning: false,
    },
  },
  embeddings: "voyageai/voyage-4",
  rerank: "voyageai/rerank-2.5",
}

function day(): AhqEvent[] {
  nextId = 1
  return [
    event("sim.started", 0, {
      actor: "simulator",
      occurred_at: SIM,
      payload: { run_id: "sim_1" },
    }),
    event("ticket.opened", 0.5, {
      actor: "simulator",
      occurred_at: SIM,
      payload: { for_agents: false },
    }),
    event("ticket.opened", 0.8, {
      actor: "simulator",
      occurred_at: SIM,
      payload: { for_agents: true },
    }),
    work("work.created", 1, "simulator", { kind: "ticket" }),
    work("model.called", 2.5, "guard", {
      seconds: 0.5,
      cost_usd: 0.001,
      model: "claude-haiku-4-5",
    }),
    work("model.called", 3.5, "dispatcher", { seconds: 0.5, cost_usd: 0.001 }),
    work("work.routed", 3.6, "dispatcher", { route: "support" }),
    work("model.called", 6, "support", { seconds: 2, cost_usd: 0.01, pass: 1 }),
    work("tool.called", 6.2, "support", {
      tool: "find_user_id_by_email",
      seconds: 0.1,
      verdict: "allowed",
      ok: true,
      cached: false,
      result: { text: "ada_1" },
    }),
    work("tool.called", 7.5, "support", {
      tool: "get_order_details",
      seconds: 0,
      verdict: "refused",
      reason: "That order belongs to another customer.",
      ok: false,
      cached: false,
      result: {},
    }),
    work("approval.requested", 9, "runtime", {
      action: "return_delivered_order_items",
      reason: "Refund over $100",
    }),
    work("approval.decided", 14, "operator", { verdict: "approve" }),
    work("ticket.replied", 16, "support", {
      status: "resolved",
      summary: "Returned the items.",
    }),
    work("work.completed", 16.1, "runtime"),
    work("qa.reviewed", 19, "qa", {
      agent: "support",
      seconds: 1,
      cost_usd: 0.004,
      verdicts: { policy: "pass" },
    }),
  ]
}

describe("the timeline of a day", () => {
  const timeline = buildTimeline(day(), DEMO)

  it("follows a ticket from the customers through triage to Support and to you and back", () => {
    const [ticket] = timeline.items
    expect(ticket.stops.map((stop) => stop.node)).toEqual([
      "customers",
      "screen",
      "dispatcher",
      "support",
      "you",
      "support",
    ])
    expect(ticket.waits).toEqual([{ start: 9000, end: 14000 }])
    expect(ticket.endAt).toBe(16100)
  })

  it("draws each call for as long as it took, out to the model or the data it used", () => {
    const screen = timeline.beams.find((beam) => beam.node === "screen")
    expect(screen).toMatchObject({
      start: 2000,
      end: 2500,
      row: "claude-haiku-4-5",
    })
    expect(timeline.packets.map((p) => [p.store, p.status])).toEqual([
      ["orders", "ok"],
      ["orders", "refused"],
    ])
    expect(timeline.wires.map((wire) => wire.key)).toContain("support>orders")
  })

  it("marks the day's chapters", () => {
    expect(timeline.chapters.map((chapter) => chapter.label)).toEqual([
      "Day starts",
      "Waits for you",
    ])
  })
})

describe("a frame of the map", () => {
  const timeline = buildTimeline(day(), DEMO)

  it("shows the ticket at the input check while the input check's call runs", () => {
    const frame = frameAt(timeline, 2200)
    const dot = frame.dots.find((d) => d.key === "wi_1")
    expect(dot).toMatchObject({
      x: 560,
      y: 166,
      tone: "ticket",
      workItemId: "wi_1",
    })
    expect(frame.nodes.screen.tone).toBe("live")
    expect(
      frame.wires.find((w) => w.key === "screen>claude-haiku-4-5")?.state
    ).toBe("model")
    expect(frame.rows.find((row) => row.id === "claude-haiku-4-5")?.live).toBe(
      1
    )
  })

  it("shows a tool call going out with its label, and a refused one stopping short in red", () => {
    const allowed = frameAt(timeline, 6500)
    expect(allowed.packets).toHaveLength(1)
    expect(allowed.tags[0].text).toBe("find_user_id_by_email · 0.10 s")
    const refused = frameAt(timeline, 7800)
    expect(refused.packets[0].status).toBe("refused")
    expect(refused.nodes.support.tone).toBe("red")
    expect(refused.wires.find((w) => w.key === "support>orders")?.state).toBe(
      "refused"
    )
  })

  it("parks the ticket with you, pulsing, while it waits for approval", () => {
    const frame = frameAt(timeline, 11_000)
    const dot = frame.dots.find((d) => d.key === "wi_1")
    expect(dot?.waiting).toBe(true)
    expect([dot?.x, dot?.y]).toEqual([680, 516])
    expect(frame.nodes.you.stat).toBe("1 waiting · 0 decided")
    expect(frame.caption?.text).toMatch(/waits for your approval/)
  })

  it("counts what the team did by the end", () => {
    const frame = frameAt(timeline, timeline.duration)
    expect(frame.nodes.customers.stat).toBe("2 today · 1 to the agents")
    expect(frame.nodes.screen.stat).toBe("checked 1 · held 0")
    expect(frame.nodes.support.stat).toBe("0 open · 1 resolved")
    expect(frame.nodes.support.cost).toBe("$0.010")
    expect(frame.nodes.you.stat).toBe("0 waiting · 1 decided")
    expect(frame.nodes.qa.stat).toBe("1 reviewed")
    expect(frame.nodes.qa.cost).toBe("$0.004")
    expect(frame.stores.orders.stat).toBe("2 calls · 1 refused")
    expect(nextActivity(timeline, timeline.duration - 1)).toBe(
      timeline.duration
    )
    expect(nextActivity(timeline, 2200)).toBeNull()
    expect(nextActivity(timeline, 16_500)).toBeNull()
    expect(nextActivity(timeline, 17_150)).toBe(17_200)
    expect(frame.totals.modelCalls).toBe(4)
    expect(frame.dots.find((d) => d.key === "wi_1")).toBeUndefined()
  })

  it("tells the simulated time from the simulator's events", () => {
    expect(simulatedAt(timeline, -1)).toBeNull()
    expect(frameAt(timeline, 0).clock).toBe("08:00")
  })
})

describe("the rails and the clock", () => {
  it("gives each model a row with the roles it plays, and retrieval its own", () => {
    const { rows, rowOf } = modelRail(DEMO)
    expect(rows.map((row) => [row.title, row.roles.join(", ")])).toEqual([
      ["Haiku 4.5", "input check, Dispatcher"],
      ["Sonnet 5", "Support, Ops, Insights"],
      ["gpt-6-luna", "simulated customers"],
      ["gpt-6-sol", "QA reviewer"],
      ["voyage-4, rerank-2.5", "knowledge search"],
    ])
    expect(rows[1].reasoning).toBe(true)
    expect(rowOf("ops")).toBe("claude-sonnet-5")
  })

  it("groups the offline rules the way a real lineup splits", () => {
    const fake = { key: "fake", id: "fake", provider: "fake", reasoning: false }
    const lineup: Lineup = {
      ...DEMO,
      roles: Object.fromEntries(
        Object.keys(DEMO.roles).map((role) => [role, fake])
      ),
    }
    expect(modelRail(lineup).rows.map((row) => row.title)).toEqual([
      "Rules",
      "Rules",
      "Rules",
      "Rules",
      "voyage-4, rerank-2.5",
    ])
  })

  it("times the simulator's events without a recorded time by their neighbours", () => {
    const [started, opened, , created] = day()
    const times = wallTimes([
      { ...started, recorded_at: null },
      { ...created },
      { ...opened, recorded_at: null },
    ])
    expect(times).toEqual([T0 + 1000, T0 + 1000, T0 + 1000])
    expect(storeOf("knowledge_search")).toBe("knowledge")
    expect(storeOf("analytics_run_sql")).toBe("analytics")
    expect(storeOf("flag_pattern")).toBeNull()
  })
})

describe("a timeline that starts part way through the day", () => {
  it("draws work whose start it never saw, from its first event", () => {
    const events = day().filter((e) => e.kind !== "work.created" && e.id > 5)
    const timeline = buildTimeline(events, DEMO)
    const [item] = timeline.items
    expect(item.id).toBe("wi_1")
    expect(item.stops[0].node).toBe("dispatcher")
  })
})

describe("the live clock", () => {
  const MINUTE = 60_000
  const at = (wall: number, minutes: number, extra: object = {}) => ({
    wall,
    sim: minutes * MINUTE,
    ...extra,
  })

  it("carries on at the day's pace past the last event, for a while", () => {
    const timeline = {
      sim: [at(0, 0, { pace: 150 }), at(4_000, 10), at(8_000, 20)],
    } as unknown as Timeline
    expect(simulatedAt(timeline, 10_000)).toBe(20 * MINUTE)
    expect(simulatedAt(timeline, 10_000, 20_000)).toBe(25 * MINUTE)
    expect(simulatedAt(timeline, 60_000, 20_000)).toBe(70 * MINUTE)
  })

  it("starts at the pace the day was started at", () => {
    const timeline = { sim: [at(0, 0, { pace: 150 })] } as unknown as Timeline
    expect(simulatedAt(timeline, 1_000, 20_000)).toBe(2.5 * MINUTE)
  })

  it("stands still once the day is paused or over", () => {
    const timeline = {
      sim: [at(0, 0, { pace: 150 }), at(8_000, 20, { halt: true })],
    } as unknown as Timeline
    expect(simulatedAt(timeline, 12_000, 20_000)).toBe(20 * MINUTE)
  })

  it("measures the pace on the current day only", () => {
    const timeline = {
      sim: [
        at(0, 600, { halt: true }),
        at(5_000, 0, { pace: 150 }),
        at(10_000, 10),
      ],
    } as unknown as Timeline
    expect(simulatedAt(timeline, 12_000, 20_000)).toBe(14 * MINUTE)
  })
})

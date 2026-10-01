import { describe, expect, it } from "vitest"

import type { AhqEvent } from "@/lib/api/types"
import { dayAxis } from "@/lib/scene/day"
import { buildTimeline } from "@/lib/scene/timeline"

const WALL = Date.parse("2026-09-28T15:00:00Z")
const STORE = Date.parse("2026-06-15T12:00:00Z")
const MINUTE = 60_000
let nextId = 1

function simulator(
  kind: AhqEvent["kind"],
  seconds: number,
  minutes: number,
  payload: Record<string, unknown> = {}
): AhqEvent {
  return {
    id: nextId++,
    kind,
    occurred_at: new Date(STORE + minutes * MINUTE).toISOString(),
    recorded_at: new Date(WALL + seconds * 1000).toISOString(),
    actor: "simulator",
    work_item_id: null,
    payload,
  }
}

function agent(seconds: number): AhqEvent {
  const at = new Date(WALL + seconds * 1000).toISOString()
  return {
    id: nextId++,
    kind: "model.called",
    occurred_at: at,
    recorded_at: at,
    actor: "support",
    work_item_id: "wi_1",
    payload: { model: "claude-sonnet-5-5", seconds: 1, cost_usd: 0.01 },
  }
}

function day() {
  const events = [
    simulator("sim.started", 0, 0, { tick_minutes: 5, tick_seconds: 2 }),
    simulator("ticket.opened", 2, 5),
    simulator("ticket.opened", 4, 10),
    simulator("sim.paused", 5, 12.5),
    simulator("sim.resumed", 15, 12.5, { tick_minutes: 5, tick_seconds: 2 }),
    simulator("ticket.opened", 17, 15),
    simulator("sim.finished", 20, 20),
    agent(22),
  ]
  const timeline = buildTimeline(events, null)
  return { timeline, axis: dayAxis(timeline) }
}

describe("a recorded day's own clock", () => {
  it("starts when the day did, even when its first tick is recorded at the same moment", () => {
    const events = [
      simulator("sim.started", 0, 0),
      simulator("ticket.opened", 0, 4),
      simulator("ticket.opened", 2, 9),
    ]
    const axis = dayAxis(buildTimeline(events, null))
    expect(axis.start).toBe(STORE)
    expect(axis.storeAt(2000)).toBe(STORE + 9 * MINUTE)
  })

  it("spans the store's day, not the run", () => {
    const { axis } = day()
    expect(axis.start).toBe(STORE)
    expect(axis.end).toBe(STORE + 20 * MINUTE)
  })

  it("reads the store's time along the run, and stands still while the day was paused", () => {
    const { axis } = day()
    expect(axis.storeAt(0)).toBe(STORE)
    expect(axis.storeAt(3000)).toBe(STORE + 7.5 * MINUTE)
    expect(axis.storeAt(10_000)).toBe(STORE + 12.5 * MINUTE)
    expect(axis.storeAt(22_000)).toBe(STORE + 20 * MINUTE)
  })

  it("finds where in the run the store's clock read a time", () => {
    const { axis } = day()
    expect(axis.wallAt(STORE + 10 * MINUTE)).toBe(4000)
    expect(axis.wallAt(STORE + 12.5 * MINUTE)).toBe(5000)
    expect(axis.wallAt(STORE - MINUTE)).toBe(0)
  })

  it("plays at a multiple of real time on the store's clock", () => {
    const { axis } = day()
    expect(axis.rate(3000, 1440)).toBeCloseTo(9.6)
    expect(axis.rate(3000, 120)).toBeCloseTo(0.8)
    expect(axis.rate(10_000, 120)).toBe(2)
    expect(axis.rate(10_000, 1440)).toBeLessThanOrEqual(20)
    expect(axis.realBetween(2000, 4000, 1440)).toBeCloseTo(2000 / 9.6)
  })

  it("shows the run's own moments on the store's clock, and keeps the store's", () => {
    const { axis } = day()
    expect(axis.toStore(WALL + 3000)).toBe(STORE + 7.5 * MINUTE)
    expect(axis.toStore(STORE + 5 * MINUTE)).toBe(STORE + 5 * MINUTE)
    const placed = STORE - 20 * 24 * 60 * MINUTE
    expect(axis.toStore(placed)).toBe(placed)
    expect(axis.toStore(WALL - 60 * MINUTE)).toBe(STORE - 60 * MINUTE)
  })
})

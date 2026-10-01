import type { SimAnchor, Timeline } from "@/lib/scene/timeline"

export const DAY_SPEEDS = [120, 240, 1440] as const
export type DaySpeed = (typeof DAY_SPEEDS)[number]

const MAX_WALL_RATE = 20
const MIN_FROZEN_RATE = 2

type Point = { wall: number; sim: number }

export type DayAxis = {
  start: number
  end: number
  storeAt: (t: number) => number
  wallAt: (store: number) => number
  rate: (t: number, speed: number) => number
  realBetween: (from: number, to: number, speed: number) => number
  toStore: (epoch: number) => number
}

function points(anchors: readonly SimAnchor[], duration: number): Point[] {
  const sorted = [...anchors].sort((a, b) => a.wall - b.wall)
  const known: Point[] = []
  let high = Number.NEGATIVE_INFINITY
  for (const anchor of sorted) {
    high = Math.max(high, anchor.sim)
    const last = known[known.length - 1]
    if (last && anchor.wall - last.wall < 1) {
      last.sim = known.length === 1 ? last.sim : high
    } else {
      known.push({ wall: anchor.wall, sim: high })
    }
  }
  if (known.length === 0) {
    return known
  }
  if (known[0].wall > 0) {
    known.unshift({ wall: 0, sim: known[0].sim })
  }
  const last = known[known.length - 1]
  if (duration > last.wall) {
    known.push({ wall: duration, sim: last.sim })
  }
  return known
}

function segmentAt(known: readonly Point[], t: number): number {
  let low = 0
  let high = known.length - 2
  while (low < high) {
    const middle = (low + high + 1) >> 1
    if (known[middle].wall <= t) {
      low = middle
    } else {
      high = middle - 1
    }
  }
  return Math.max(0, low)
}

export function dayAxis(timeline: Timeline): DayAxis {
  const duration = Math.max(1, timeline.duration)
  const origin = timeline.origin
  const known = points(timeline.sim, duration)
  if (known.length < 2) {
    known.splice(
      0,
      known.length,
      { wall: 0, sim: origin },
      { wall: duration, sim: origin + duration }
    )
  }
  const start = known[0].sim
  const end = known[known.length - 1].sim
  let running = 0
  for (let i = 0; i + 1 < known.length; i++) {
    if (known[i + 1].sim > known[i].sim) {
      running += known[i + 1].wall - known[i].wall
    }
  }
  const pace = running > 0 ? (end - start) / running : 1

  const storeAt = (t: number): number => {
    const i = segmentAt(known, t)
    const a = known[i]
    const b = known[i + 1]
    if (t <= a.wall || b.wall <= a.wall) {
      return a.sim
    }
    if (t >= b.wall) {
      return b.sim
    }
    return a.sim + ((t - a.wall) / (b.wall - a.wall)) * (b.sim - a.sim)
  }

  const wallAt = (store: number): number => {
    if (store <= start) {
      return 0
    }
    for (let i = 0; i + 1 < known.length; i++) {
      const a = known[i]
      const b = known[i + 1]
      if (store <= b.sim && b.sim > a.sim) {
        return a.wall + ((store - a.sim) / (b.sim - a.sim)) * (b.wall - a.wall)
      }
    }
    return duration
  }

  const segmentRate = (i: number, speed: number): number => {
    const a = known[i]
    const b = known[i + 1]
    const wall = b.wall - a.wall
    const sim = b.sim - a.sim
    if (wall <= 0) {
      return MAX_WALL_RATE
    }
    if (sim <= 0) {
      return Math.min(MAX_WALL_RATE, Math.max(MIN_FROZEN_RATE, speed / pace))
    }
    return Math.min(MAX_WALL_RATE, (speed * wall) / sim)
  }

  const rate = (t: number, speed: number): number =>
    segmentRate(segmentAt(known, t), speed)

  const realBetween = (from: number, to: number, speed: number): number => {
    let total = 0
    let t = from
    while (t < to) {
      const i = segmentAt(known, t)
      const stop = Math.min(to, i + 1 < known.length ? known[i + 1].wall : to)
      const edge = stop > t ? stop : to
      total += (edge - t) / segmentRate(i, speed)
      t = edge
    }
    return total
  }

  const toStore = (epoch: number): number => {
    const fromDay =
      epoch < start ? start - epoch : epoch > end ? epoch - end : 0
    const wall = epoch - origin
    const fromRun = wall < 0 ? -wall : wall > duration ? wall - duration : 0
    if (fromDay <= fromRun) {
      return epoch
    }
    if (wall < 0) {
      return start + wall
    }
    if (wall > duration) {
      return end + (wall - duration)
    }
    return storeAt(wall)
  }

  return { start, end, storeAt, wallAt, rate, realBetween, toStore }
}

import { describe, expect, it } from "vitest"

import type { AhqEvent } from "@/lib/api/types"
import { latestCursor, mergeEvents } from "@/lib/live/feed"

function event(id: number, kind: AhqEvent["kind"] = "work.created"): AhqEvent {
  return {
    id,
    kind,
    occurred_at: "2026-01-01T00:00:00Z",
    work_item_id: null,
    actor: null,
    payload: {},
  }
}

describe("mergeEvents", () => {
  it("keeps the newest first", () => {
    const merged = mergeEvents([event(1)], [event(3), event(2)])
    expect(merged.map((e) => e.id)).toEqual([3, 2, 1])
  })

  it("drops duplicates delivered after a reconnect", () => {
    const merged = mergeEvents([event(2), event(1)], [event(2), event(3)])
    expect(merged.map((e) => e.id)).toEqual([3, 2, 1])
  })

  it("forgets what came before the activity was cleared", () => {
    const merged = mergeEvents(
      [event(2), event(1)],
      [event(4), event(3, "activity.cleared")]
    )
    expect(merged.map((e) => e.id)).toEqual([4, 3])
  })

  it("caps the feed", () => {
    const merged = mergeEvents([], [event(1), event(2), event(3)], 2)
    expect(merged.map((e) => e.id)).toEqual([3, 2])
  })
})

describe("latestCursor", () => {
  it("is the highest id, or zero for an empty feed", () => {
    expect(latestCursor([event(4), event(9), event(2)])).toBe(9)
    expect(latestCursor([])).toBe(0)
  })
})

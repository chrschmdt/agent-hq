import type { AhqEvent } from "@/lib/api/types"

export const FEED_LIMIT = 200
export const KEEP_LIMIT = 2000

export function mergeEvents(
  current: readonly AhqEvent[],
  incoming: readonly AhqEvent[],
  limit = FEED_LIMIT
): AhqEvent[] {
  if (incoming.length === 0) {
    return current as AhqEvent[]
  }
  const byId = new Map<number, AhqEvent>()
  for (const event of [...incoming, ...current]) {
    if (!byId.has(event.id)) {
      byId.set(event.id, event)
    }
  }
  const merged = [...byId.values()].sort((a, b) => b.id - a.id)
  const cleared = merged.findIndex((event) => event.kind === "activity.cleared")
  return merged.slice(0, cleared === -1 ? limit : Math.min(limit, cleared + 1))
}

export function latestCursor(events: readonly AhqEvent[]): number {
  return events.reduce((max, event) => Math.max(max, event.id), 0)
}

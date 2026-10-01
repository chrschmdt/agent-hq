import type { WorkItem, WorkStatus } from "@/lib/api/types"

export function workTitle(item: WorkItem): string {
  const input = item.input as Record<string, unknown>
  switch (item.kind) {
    case "ticket":
      return `Ticket ${String(input.ticket_id ?? "")}`
    case "alert": {
      const alert = input.alert as
        { metric?: string; segment?: Record<string, string> } | undefined
      const segment = Object.values(alert?.segment ?? {}).join(", ")
      return segment ? `Alert: ${segment}` : "KPI alert"
    }
    case "flag": {
      const flag = input.flag as
        { topic?: string; summary?: string } | undefined
      return flag?.topic ? `Flag: ${flag.topic}` : "Flagged pattern"
    }
    default:
      return `${item.kind} run`
  }
}

export function workDetail(item: WorkItem): string | null {
  const input = item.input as Record<string, unknown>
  if (item.kind === "flag") {
    const flag = input.flag as { summary?: string } | undefined
    return flag?.summary ?? null
  }
  if (item.kind === "alert") {
    const alert = input.alert as
      | {
          metric?: string
          value?: number
          baseline?: number
          window_hours?: number
        }
      | undefined
    if (!alert?.metric) {
      return null
    }
    const expected = (alert.baseline ?? 0).toFixed(1)
    return `${alert.value} ${alert.metric.replaceAll("_", " ")} in ${alert.window_hours} hours, ${expected} expected`
  }
  return null
}

export type Column = { key: string; title: string; statuses: WorkStatus[] }

export const COLUMNS: Column[] = [
  { key: "active", title: "In progress", statuses: ["new", "running"] },
  { key: "approval", title: "Waiting on you", statuses: ["waiting_approval"] },
  {
    key: "customer",
    title: "Waiting on the customer",
    statuses: ["waiting_customer"],
  },
  { key: "done", title: "Done", statuses: ["done"] },
  {
    key: "stopped",
    title: "With a person, or stopped",
    statuses: ["escalated", "failed", "cancelled"],
  },
]

export function byColumn(
  items: readonly WorkItem[]
): Record<string, WorkItem[]> {
  const columns: Record<string, WorkItem[]> = Object.fromEntries(
    COLUMNS.map((c) => [c.key, []])
  )
  for (const item of items) {
    const column = COLUMNS.find((c) => c.statuses.includes(item.status))
    if (column) {
      columns[column.key].push(item)
    }
  }
  return columns
}

import type { PathStep, WorkStatus } from "@/lib/api/types"

const ENDED: WorkStatus[] = [
  "done",
  "escalated",
  "waiting_customer",
  "failed",
  "cancelled",
]

const ENTER = ["__start__", "entry", "screen"]

export function runRoute(
  path: readonly PathStep[],
  status: WorkStatus
): string[] {
  const route = [...ENTER]
  for (const step of path) {
    if (route.at(-1) === "finalize" && step.node !== "finalize") {
      route.push("__end__", ...ENTER)
    }
    if (route.at(-1) !== step.node) {
      route.push(step.node)
    }
  }
  if (ENDED.includes(status)) {
    if (route.at(-1) !== "finalize") {
      route.push("finalize")
    }
    route.push("__end__")
  }
  return route
}

export function travelled(route: readonly string[]): Set<string> {
  const edges = new Set<string>()
  for (let index = 1; index < route.length; index += 1) {
    edges.add(`${route[index - 1]}->${route[index]}`)
  }
  return edges
}

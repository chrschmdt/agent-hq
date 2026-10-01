import type { EventKind } from "@/lib/api/types"

const EVERYTHING = [
  "work",
  "runs",
  "agents",
  "scorecards",
  "value",
  "approvals",
  "incidents",
  "proposals",
  "sim",
  "limits",
  "versions",
  "evals",
  "qa",
]

export function queriesFor(kind: EventKind): string[] {
  if (kind === "activity.cleared") {
    return EVERYTHING
  }
  const [area] = kind.split(".")
  switch (area) {
    case "work":
    case "ticket":
      return ["work", "runs", "agents", "scorecards", "value"]
    case "approval":
      return ["approvals", "work", "runs", "value"]
    case "incident":
      return ["incidents", "runs", "value"]
    case "proposal":
    case "kb":
      return ["proposals", "runs"]
    case "sim":
      return ["sim"]
    case "agent":
      return ["runs", "agents", "limits"]
    case "version":
      return ["versions", "agents", "scorecards"]
    case "eval":
      return ["evals", "versions"]
    case "qa":
      return ["qa", "scorecards", "runs"]
    case "limit":
    case "breaker":
      return ["limits", "agents"]
    default:
      return []
  }
}

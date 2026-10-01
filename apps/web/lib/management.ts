import type {
  Metric,
  MetricDef,
  ReviewRecord,
  VersionStatus,
} from "@/lib/api/types"
import { percent, usd } from "@/lib/format"

export function metricText(metric: Metric | undefined, def: MetricDef): string {
  if (!metric || metric.value === null || metric.value === undefined) {
    return "-"
  }
  const value = metric.value
  switch (def.unit) {
    case "rate":
      return percent(value)
    case "usd":
      return usd(value)
    case "seconds":
      return `${value.toFixed(1)}s`
    case "tokens":
      return Math.round(value).toLocaleString("en-US")
    case "count":
      return String(Math.round(value))
  }
}

const NEGLIGIBLE: Record<MetricDef["unit"], number> = {
  rate: 0.005,
  usd: 0.0001,
  seconds: 0.05,
  tokens: 1,
  count: 0.5,
}

export function comparison(
  def: MetricDef,
  value: number | null | undefined,
  against: number | null | undefined,
  tolerance = 0.02
): "better" | "worse" | "same" | null {
  if (value === null || value === undefined) {
    return null
  }
  if (against === null || against === undefined) {
    return null
  }
  const difference = value - against
  const scale = Math.max(Math.abs(against), def.unit === "rate" ? 1 : 1e-9)
  if (
    Math.abs(difference) <= NEGLIGIBLE[def.unit] ||
    Math.abs(difference / scale) <= tolerance
  ) {
    return "same"
  }
  return difference > 0 === (def.direction === "higher") ? "better" : "worse"
}

export type DiffLine = {
  kind: "add" | "remove" | "hunk" | "file" | "same"
  text: string
}

export function diffLines(lines: string[]): DiffLine[] {
  return lines.map((text) => {
    if (text.startsWith("+++") || text.startsWith("---")) {
      return { kind: "file", text }
    }
    if (text.startsWith("@@")) {
      return { kind: "hunk", text }
    }
    if (text.startsWith("+")) {
      return { kind: "add", text }
    }
    if (text.startsWith("-")) {
      return { kind: "remove", text }
    }
    return { kind: "same", text }
  })
}

export function agreement(
  labels: Record<string, "pass" | "fail">,
  review: ReviewRecord
): Record<string, boolean> {
  const verdicts = new Map(
    review.criteria.map((criterion) => [
      criterion.criterion_id,
      criterion.verdict,
    ])
  )
  return Object.fromEntries(
    Object.entries(labels).map(([id, verdict]) => [
      id,
      verdicts.get(id) === verdict,
    ])
  )
}

export const STATUS_ORDER: Record<VersionStatus, number> = {
  live: 0,
  canary: 1,
  evaluated: 2,
  draft: 3,
  retired: 4,
}

export function versionActions(
  status: VersionStatus
): ("gate" | "canary" | "promote" | "rollback" | "retire")[] {
  switch (status) {
    case "draft":
      return ["gate", "canary", "promote", "retire"]
    case "evaluated":
      return ["gate", "canary", "promote", "retire"]
    case "canary":
      return ["promote", "rollback"]
    case "retired":
      return ["canary"]
    case "live":
      return []
  }
}

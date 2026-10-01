import { LinkedText } from "@/components/records/record-drawer"
import { Badge } from "@/components/ui/badge"
import type { AhqEvent } from "@/lib/api/types"
import { STORE_TIME_ZONE, versionsIn } from "@/lib/format"
import { cn } from "@/lib/utils"

const TONE: Record<string, string> = {
  work: "bg-primary/10 text-primary",
  model: "bg-chart-2/15 text-foreground",
  tool: "bg-chart-3/15 text-foreground",
  approval: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  ticket: "bg-chart-4/15 text-foreground",
  order: "bg-chart-5/15 text-foreground",
  parcel: "bg-chart-5/15 text-foreground",
  agent: "bg-primary/10 text-primary",
  incident: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  proposal: "bg-chart-1/15 text-foreground",
  kb: "bg-chart-1/15 text-foreground",
  version: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  eval: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  qa: "bg-chart-2/15 text-foreground",
}

function tone(event: AhqEvent): string {
  const payload = event.payload as Record<string, unknown>
  if (event.kind === "work.failed") {
    return "bg-destructive/10 text-destructive"
  }
  if (
    (event.kind === "parcel.delivered" && payload.late) ||
    event.kind === "work.escalated" ||
    event.kind === "kpi.alert" ||
    event.kind === "pattern.flagged" ||
    event.kind === "version.rolled_back" ||
    event.kind === "agent.paused" ||
    event.kind === "limit.reached" ||
    event.kind === "breaker.opened" ||
    event.kind === "work.deferred"
  ) {
    return TONE.approval
  }
  if (event.kind === "guardrail.blocked") {
    return "bg-destructive/10 text-destructive"
  }
  return TONE[event.kind.split(".")[0]] ?? "bg-muted text-muted-foreground"
}

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: STORE_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function summary(event: AhqEvent): string {
  const payload = event.payload as Record<string, unknown>
  if (event.kind === "model.called") {
    const agent = payload.agent ? `${payload.agent}, ` : ""
    return `${agent}${payload.model}, $${Number(payload.cost_usd ?? 0).toFixed(5)}`
  }
  if (event.kind === "tool.called") {
    const name = payload.server
      ? `${payload.server}.${payload.tool}`
      : String(payload.tool)
    return payload.ok === false ? `${name}, error` : name
  }
  if (event.kind === "approval.requested") {
    return String(payload.reason ?? "")
  }
  if (event.kind === "approval.decided") {
    return String(payload.verdict ?? "")
  }
  if (
    event.kind === "work.completed" ||
    event.kind === "work.waiting_customer" ||
    event.kind === "work.escalated" ||
    event.kind === "ticket.closed"
  ) {
    return String(payload.outcome ?? "")
  }
  if (event.kind === "work.cancelled") {
    return String(payload.reason ?? "")
  }
  if (event.kind === "ticket.opened") {
    return String(payload.subject ?? "")
  }
  if (event.kind === "ticket.message") {
    return String(payload.body ?? "")
  }
  if (event.kind === "ticket.replied") {
    const citations = Array.isArray(payload.citations)
      ? payload.citations.length
      : 0
    const cited = citations ? ` (${citations} cited)` : ""
    return `${String(payload.reply ?? "")}${cited}`
  }
  if (event.kind === "ticket.rated") {
    return `CSAT ${payload.csat}`
  }
  if (event.kind === "order.shipped") {
    return `${payload.order_id} with ${payload.carrier}`
  }
  if (event.kind === "parcel.delivered") {
    return `${payload.order_id} by ${payload.carrier}${payload.late ? ", late" : ""}`
  }
  if (event.kind.startsWith("sim.")) {
    return `${payload.scenario}, seed ${payload.seed}`
  }
  if (event.kind === "kpi.alert") {
    const segment = Object.values(
      (payload.segment ?? {}) as Record<string, string>
    ).join(" ")
    return `${payload.metric} for ${segment}: ${payload.value} vs ${payload.baseline} expected`
  }
  if (event.kind === "pattern.flagged") {
    return `${payload.topic}: ${String(payload.summary ?? "")}`
  }
  if (event.kind === "work.routed") {
    return `to ${payload.route}, ${payload.priority}: ${String(payload.reason ?? "")}`
  }
  if (event.kind === "agent.handoff") {
    return `${payload.from} to ${payload.to}`
  }
  if (event.kind === "incident.filed") {
    return `${payload.severity}: ${String(payload.title ?? "")}`
  }
  if (event.kind === "proposal.created") {
    return `${payload.kind}: ${String(payload.title ?? "")}`
  }
  if (event.kind === "proposal.decided") {
    return `${payload.proposal_id} ${payload.verdict}`
  }
  if (event.kind === "kb.published") {
    return `${payload.doc_id} v${payload.version}`
  }
  if (event.kind === "version.rolled_back") {
    const reasons = Array.isArray(payload.reasons)
      ? payload.reasons.join("; ")
      : ""
    return `${payload.version_id}: ${reasons}`
  }
  if (event.kind === "version.canary_started") {
    return `${payload.version_id} on ${payload.pct}%${payload.skipped_gate ? ", without the eval gate" : ""}`
  }
  if (event.kind === "version.evaluated") {
    return `${payload.version_id} ${payload.passed ? "passed" : "failed"} the eval gate`
  }
  if (event.kind.startsWith("version.")) {
    return String(payload.version_id ?? "")
  }
  if (event.kind.startsWith("eval.")) {
    return `${payload.candidate_id} against ${payload.baseline_id}, ${payload.status}`
  }
  if (event.kind === "qa.reviewed") {
    const verdicts = Object.values(
      (payload.verdicts ?? {}) as Record<string, string>
    )
    const failed = verdicts.filter((verdict) => verdict === "fail").length
    return `${payload.version_id}, ${failed} of ${verdicts.length} criteria failed`
  }
  if (event.kind === "agent.paused") {
    return `${payload.agent}: ${String(payload.reason ?? "")}`
  }
  if (event.kind === "agent.resumed") {
    return String(payload.agent ?? "")
  }
  if (event.kind === "limit.reached") {
    return String(payload.reason ?? "")
  }
  if (event.kind === "breaker.opened") {
    return `${payload.model} to ${payload.fallback}`
  }
  if (event.kind === "work.deferred") {
    return `resumes in ${Math.round(Number(payload.after_seconds ?? 0))}s: ${String(payload.reason ?? "")}`
  }
  if (event.kind === "guardrail.blocked") {
    if (payload.stage === "output") {
      const found = (payload.findings ?? []) as { kind: string }[]
      return `reply held back: ${found.map((finding) => finding.kind).join(", ")}`
    }
    return `input blocked (${payload.threat}, ${payload.by})`
  }
  if (event.kind === "models.switched") {
    return `${payload.previous} to ${payload.profile}`
  }
  if (event.kind === "activity.cleared") {
    const versions = payload.versions ? ", agents back to version 1" : ""
    return `${Number(payload.records ?? 0).toLocaleString("en-US")} records${versions}`
  }
  return ""
}

export function EventRow({ event, at }: { event: AhqEvent; at?: string }) {
  return (
    <li className="grid grid-cols-[4.5rem_10rem_1fr] items-center gap-3 px-4 py-2 text-sm">
      <span className="font-mono text-xs text-muted-foreground tabular-nums">
        {time(at ?? event.occurred_at)}
      </span>
      <Badge className={cn("justify-self-start font-mono", tone(event))}>
        {event.kind}
      </Badge>
      <span className="min-w-0 truncate text-muted-foreground">
        {event.work_item_id ? (
          <span className="font-mono text-xs">{event.work_item_id}</span>
        ) : null}
        {summary(event) ? (
          <span className="ml-2 text-foreground">
            <LinkedText text={versionsIn(summary(event))} />
          </span>
        ) : null}
      </span>
    </li>
  )
}

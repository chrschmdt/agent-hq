"use client"

import { VerdictBadge } from "@/components/quality/verdict-badge"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import type { AgentRun, AgentSummary, ReviewRecord } from "@/lib/api/types"
import { usd, words } from "@/lib/format"
import { type Inspection, name } from "@/lib/inspector/passes"
import { cn } from "@/lib/utils"

const CHIP = "border-transparent font-medium"
const GOOD = "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
const LIVE =
  "bg-[color-mix(in_oklch,var(--map-live)_14%,transparent)] text-[var(--map-live)]"
const BAD = "bg-destructive/10 text-destructive"

export function BeforeLoopCard({ inspection }: { inspection: Inspection }) {
  const { screening, route } = inspection
  if (!screening && !route) {
    return null
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Before the loop</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        {screening ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">Input check</span>
              <Badge
                variant="outline"
                className={cn(CHIP, screening.blocked ? BAD : GOOD)}
              >
                {screening.blocked
                  ? `held: ${words(screening.threat)}`
                  : "no threat"}
              </Badge>
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {screening.by === "pattern" ? "pattern" : "classifier"}
                {screening.seconds !== null
                  ? `, ${screening.seconds.toFixed(1)} s`
                  : ""}
              </span>
            </div>
            {screening.reason ? (
              <p className="text-muted-foreground italic">{screening.reason}</p>
            ) : null}
          </div>
        ) : null}
        {route ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">Dispatcher</span>
              <Badge variant="outline" className={cn(CHIP, LIVE)}>
                to {name(route.route === "human" ? "a person" : route.route)}
              </Badge>
              {route.priority ? (
                <span className="text-xs text-muted-foreground">
                  priority {route.priority}
                </span>
              ) : null}
              {route.seconds !== null ? (
                <span className="ml-auto font-mono text-xs text-muted-foreground">
                  {route.seconds.toFixed(1)} s
                </span>
              ) : null}
            </div>
            {route.reason ? (
              <p className="text-muted-foreground italic">{route.reason}</p>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export function ChecksCard({
  inspection,
  replied,
}: {
  inspection: Inspection
  replied: boolean
}) {
  const { cited, problems } = inspection.citations
  if (!replied && inspection.heldReplies === 0) {
    return null
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Checks on the replies</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex items-start gap-2">
          <Badge
            variant="outline"
            className={cn(CHIP, inspection.heldReplies ? BAD : GOOD)}
          >
            {inspection.heldReplies
              ? `held ${inspection.heldReplies}`
              : "passed"}
          </Badge>
          <span>
            Reply check:{" "}
            {inspection.heldReplies
              ? "a reply named another customer or held a link."
              : "no other customer's details, no links."}
          </span>
        </div>
        <div className="flex items-start gap-2">
          <Badge
            variant="outline"
            className={cn(CHIP, problems.length ? BAD : GOOD)}
          >
            {problems.length
              ? `${problems.length} problems`
              : cited.length
                ? "valid"
                : "none cited"}
          </Badge>
          <span className="min-w-0">
            Citations{cited.length ? ": " : "."}
            {cited.map((citation) => (
              <span
                key={citation}
                className="mr-1.5 font-mono text-xs text-[var(--map-live)]"
              >
                {citation}
              </span>
            ))}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

export function LimitsCard({
  runs,
  agents,
}: {
  runs: AgentRun[]
  agents: AgentSummary[]
}) {
  const looped = runs.filter((run) => run.agent !== "dispatcher")
  if (looped.length === 0) {
    return null
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Limits</CardTitle>
        <CardDescription>
          Each agent stops at its own limits, and the work then goes to a
          person.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        {looped.map((run) => {
          const spec = agents.find((agent) => agent.name === run.agent)
          const calls = spec
            ? Math.min(100, (run.model_calls / spec.max_model_calls) * 100)
            : 0
          const cost = spec
            ? Math.min(100, (run.cost_usd / spec.max_usd) * 100)
            : 0
          return (
            <div key={run.agent} className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold">{name(run.agent)}</span>
                <span className="text-xs text-muted-foreground">
                  {run.stop_reason
                    ? `stopped: ${words(run.stop_reason)}`
                    : words(run.outcome)}
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-xs">
                  <span>Model calls</span>
                  <span className="font-mono tabular-nums">
                    {run.model_calls}
                    {spec ? ` of ${spec.max_model_calls}` : ""}
                  </span>
                </div>
                <Progress value={calls} />
              </div>
              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-xs">
                  <span>Cost</span>
                  <span className="font-mono tabular-nums">
                    {usd(run.cost_usd)}
                    {spec ? ` of ${usd(spec.max_usd)}` : ""}
                  </span>
                </div>
                <Progress value={cost} />
              </div>
              <p className="font-mono text-[11px] text-muted-foreground">
                {run.input_tokens.toLocaleString("en-US")} tokens in,{" "}
                {(run.cached_tokens ?? 0).toLocaleString("en-US")} cached,{" "}
                {run.output_tokens.toLocaleString("en-US")} out
              </p>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

export function ReviewCard({ reviews }: { reviews: ReviewRecord[] }) {
  if (reviews.length === 0) {
    return null
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>QA review</CardTitle>
        <CardDescription>
          Critique first, then the verdict. A verdict counts once its criterion
          is calibrated.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        {reviews.map((review) => (
          <div key={review.review_id} className="flex flex-col gap-3">
            <p className="font-mono text-xs text-muted-foreground">
              {name(review.agent)}, {review.judge_model}, {words(review.reason)}
            </p>
            {review.criteria.map((criterion) => (
              <div key={criterion.criterion_id} className="flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {words(criterion.criterion_id)}
                  </span>
                  <VerdictBadge verdict={criterion.verdict} />
                </div>
                <p className="text-muted-foreground">{criterion.critique}</p>
              </div>
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

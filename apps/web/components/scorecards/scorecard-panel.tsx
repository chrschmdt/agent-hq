"use client"

import { useQuery } from "@tanstack/react-query"

import { TrendChart } from "@/components/scorecards/trend-chart"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { VersionStatusBadge } from "@/components/versions/version-status"
import { api } from "@/lib/api/client"
import type { AgentScorecards, MetricDef, VersionCard } from "@/lib/api/types"
import { percent, version, words } from "@/lib/format"
import { comparison, metricText } from "@/lib/management"
import { cn } from "@/lib/utils"

const TRENDS = [
  "escalation_rate",
  "cost_per_run",
  "latency_p95",
  "resolution_rate",
]
const CATEGORIES = ["quality", "outcome", "efficiency", "safety"] as const
const TONE = {
  better: "text-emerald-700 dark:text-emerald-300",
  worse: "text-amber-700 dark:text-amber-300",
  same: "",
}
const ACTION_TONE = {
  continue: "bg-muted",
  promote: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  rollback: "bg-destructive/10 text-destructive",
}

async function fetchScorecards(agent: string): Promise<AgentScorecards> {
  const { data } = await api.GET("/api/agents/{agent}/scorecards", {
    params: { path: { agent } },
  })
  if (!data) {
    throw new Error(`could not load the scorecards of ${agent}`)
  }
  return data
}

function Cell({
  def,
  card,
  live,
}: {
  def: MetricDef
  card: VersionCard
  live: VersionCard | undefined
}) {
  const metric = card.scorecard.metrics[def.key]
  const versus =
    live && live !== card
      ? comparison(def, metric?.value, live.scorecard.metrics[def.key]?.value)
      : null
  return (
    <TableCell
      className={cn("text-right tabular-nums", versus ? TONE[versus] : "")}
    >
      {metricText(metric, def)}
      {metric && metric.samples > 0 && def.unit === "rate" ? (
        <span className="ml-1 text-xs text-muted-foreground">
          of {metric.samples}
        </span>
      ) : null}
    </TableCell>
  )
}

export function ScorecardPanel({
  agent,
  initial,
  recorded = false,
}: {
  agent: string
  initial: AgentScorecards
  recorded?: boolean
}) {
  const { data: fetched } = useQuery({
    queryKey: ["scorecards", agent],
    queryFn: () => fetchScorecards(agent),
    initialData: initial,
    enabled: !recorded,
  })
  const data = recorded ? initial : fetched
  const cards = data.versions.slice(0, 4)
  const live = cards.find((card) => card.version.status === "live")
  const canary = cards.find((card) => card.version.status === "canary")
  const criteria = [
    ...new Set(
      cards.flatMap((card) =>
        card.scorecard.criteria.map((criterion) => criterion.criterion_id)
      )
    ),
  ]
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scorecard</CardTitle>
        <CardDescription>
          Each version on its finished runs. Colors compare a version with the
          live one; QA counts only criteria on which the reviewer is calibrated.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {canary && data.canary ? (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-sm">
            <span>
              Canary{" "}
              <span className="font-mono">
                {version(canary.version.version_id)}
              </span>
              :
            </span>
            <Badge
              variant="outline"
              className={cn(
                "border-transparent",
                ACTION_TONE[data.canary.action]
              )}
            >
              {data.canary.action}
            </Badge>
            <span className="text-muted-foreground">
              {data.canary.reasons.join("; ")}
            </span>
          </div>
        ) : null}
        {cards.length === 0 ? (
          <p className="text-sm text-muted-foreground">No versions yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                {cards.map((card) => (
                  <TableHead
                    key={card.version.version_id}
                    className="text-right"
                  >
                    <div className="flex flex-col items-end gap-1 py-1">
                      <span className="font-mono text-xs">
                        {version(card.version.version_id)}
                      </span>
                      <VersionStatusBadge
                        status={card.version.status}
                        pct={card.version.canary_pct}
                      />
                      <span className="text-xs font-normal text-muted-foreground">
                        {card.scorecard.runs} runs
                      </span>
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {CATEGORIES.flatMap((category) =>
                data.metrics
                  .filter((def) => def.category === category)
                  .map((def, index) => (
                    <TableRow key={def.key}>
                      <TableCell>
                        {index === 0 ? (
                          <span className="mr-2 text-xs text-muted-foreground uppercase">
                            {category}
                          </span>
                        ) : null}
                        {def.label}
                      </TableCell>
                      {cards.map((card) => (
                        <Cell
                          key={card.version.version_id}
                          def={def}
                          card={card}
                          live={live}
                        />
                      ))}
                    </TableRow>
                  ))
              )}
            </TableBody>
          </Table>
        )}
        {criteria.length > 0 ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">QA reviewer, by criterion</p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Criterion</TableHead>
                  {cards.map((card) => (
                    <TableHead
                      key={card.version.version_id}
                      className="text-right font-mono text-xs"
                    >
                      {version(card.version.version_id)}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {criteria.map((id) => (
                  <TableRow key={id}>
                    <TableCell className="text-xs">{words(id)}</TableCell>
                    {cards.map((card) => {
                      const score = card.scorecard.criteria.find(
                        (criterion) => criterion.criterion_id === id
                      )
                      return (
                        <TableCell
                          key={card.version.version_id}
                          className="text-right text-xs tabular-nums"
                        >
                          {score && score.raw_pass_rate !== null
                            ? `${percent(score.raw_pass_rate ?? 0)} of ${score.reviewed}`
                            : "-"}
                          {score?.corrected_pass_rate !== null &&
                          score?.corrected_pass_rate !== undefined ? (
                            <span className="ml-1 text-emerald-700 dark:text-emerald-300">
                              ({percent(score.corrected_pass_rate)} corrected)
                            </span>
                          ) : score ? (
                            <span className="ml-1 text-muted-foreground">
                              uncalibrated
                            </span>
                          ) : null}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          {TRENDS.map((key) => {
            const def = data.metrics.find((metric) => metric.key === key)
            return def ? <TrendChart key={key} def={def} cards={cards} /> : null
          })}
        </div>
      </CardContent>
    </Card>
  )
}

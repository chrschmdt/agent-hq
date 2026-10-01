"use client"

import { useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useTransition } from "react"
import { toast } from "sonner"

import { requestReview } from "@/app/actions"
import { VerdictBadge } from "@/components/quality/verdict-badge"
import { useCanAct } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { AgentRun, ReviewRecord } from "@/lib/api/types"
import { usd, version, words } from "@/lib/format"

const FINISHED = new Set([
  "resolved",
  "done",
  "routed",
  "handed_off",
  "escalated",
])

export function RunAgents({
  runs,
  reviews,
}: {
  runs: AgentRun[]
  reviews: ReviewRecord[]
}) {
  const admin = useCanAct()
  const client = useQueryClient()
  const [pending, startTransition] = useTransition()
  if (runs.length === 0) {
    return null
  }
  const ask = (run: AgentRun) =>
    startTransition(async () => {
      const result = await requestReview(run.work_item_id, run.agent)
      if (result.ok) {
        toast.success("The reviewer will look at it shortly.")
        await client.invalidateQueries({ queryKey: ["runs"] })
      } else {
        toast.error(result.error)
      }
    })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents on this run</CardTitle>
        <CardDescription>
          Each agent keeps the version that first took the work.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {runs.map((run) => {
          const review = reviews.find((item) => item.agent === run.agent)
          return (
            <div
              key={run.agent}
              className="flex flex-col gap-1.5 border-b pb-3 last:border-0 last:pb-0"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link
                  href={`/agents/${run.agent}/versions/${run.version_id}`}
                  className="font-mono text-xs underline underline-offset-4"
                >
                  {version(run.version_id)}
                </Link>
                <span className="text-xs text-muted-foreground">
                  {words(run.outcome)}
                  {run.stop_reason
                    ? `, stopped: ${words(run.stop_reason)}`
                    : ""}
                  , {usd(run.cost_usd)}
                </span>
              </div>
              {review ? (
                <div className="flex flex-wrap gap-1 text-xs">
                  {review.criteria.map((criterion) => (
                    <span
                      key={criterion.criterion_id}
                      className="flex items-center gap-1"
                      title={criterion.critique}
                    >
                      {words(criterion.criterion_id)}
                      <VerdictBadge verdict={criterion.verdict} />
                    </span>
                  ))}
                </div>
              ) : admin && FINISHED.has(run.outcome) ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={() => ask(run)}
                  disabled={pending}
                >
                  Ask the reviewer
                </Button>
              ) : (
                <p className="text-xs text-muted-foreground">Not reviewed.</p>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

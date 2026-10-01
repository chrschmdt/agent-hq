"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { EvalStatusBadge } from "@/components/evals/eval-status"
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
import { api } from "@/lib/api/client"
import type { EvalCase, EvalRun } from "@/lib/api/types"
import { moment, usd, version } from "@/lib/format"
import { cn } from "@/lib/utils"

type EvalData = { run: EvalRun; cases: EvalCase[] }

async function fetchEval(id: string): Promise<EvalData> {
  const [run, cases] = await Promise.all([
    api.GET("/api/evals/{eval_run_id}", {
      params: { path: { eval_run_id: id } },
    }),
    api.GET("/api/evals/{eval_run_id}/cases", {
      params: { path: { eval_run_id: id } },
    }),
  ])
  if (!run.data) {
    throw new Error(`could not load eval run ${id}`)
  }
  return { run: run.data, cases: cases.data ?? [] }
}

function Score({
  title,
  score,
}: {
  title: string
  score: NonNullable<EvalRun["summary"]>["candidate"]
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle className="font-mono text-base">
          {version(score.version_id)}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 text-sm">
        <p className="text-2xl font-semibold tabular-nums">{score.score}</p>
        <p className="text-muted-foreground">
          {score.metric}, {score.passed} of {score.cases} cases passed,{" "}
          {usd(score.cost_usd)}
        </p>
      </CardContent>
    </Card>
  )
}

export function EvalView({
  initial,
  live,
}: {
  initial: EvalData
  live: boolean
}) {
  const { data } = useQuery({
    queryKey: ["evals", initial.run.eval_run_id],
    queryFn: () => fetchEval(initial.run.eval_run_id),
    initialData: initial,
    enabled: live,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.run.status ?? "")
        ? 3000
        : false,
  })
  const { run, cases } = data
  const byCase = new Map<string, Record<string, EvalCase>>()
  for (const item of cases) {
    const key = `${item.case_id}#${item.trial}`
    byCase.set(key, { ...byCase.get(key), [item.version_id]: item })
  }
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <EvalStatusBadge status={run.status} />
            <span>
              {run.params.suite} on the {run.params.profile} profile,{" "}
              {run.params.cases} cases x {run.params.trials}
            </span>
          </CardTitle>
          <CardDescription>
            Requested {moment(run.created_at)} by {run.requested_by}
            {run.started_at ? `, started ${moment(run.started_at)}` : ""}
            {run.finished_at ? `, finished ${moment(run.finished_at)}` : ""}.
            Cap {usd(run.params.max_usd)}, spent {usd(run.cost_usd)}.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          {run.summary ? (
            <p>
              {run.summary.passed
                ? `Passed: ${version(run.candidate_id)} may go on to a canary.`
                : `Failed: ${run.summary.reasons.join("; ")}.`}
            </p>
          ) : null}
          {run.error ? <p className="text-destructive">{run.error}</p> : null}
          {run.url ? (
            <a
              href={run.url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-4"
            >
              The run&apos;s log
            </a>
          ) : null}
          <Link
            href={`/agents/${run.agent}/versions/${run.candidate_id}`}
            className="underline underline-offset-4"
          >
            {version(run.candidate_id)} and what it changes
          </Link>
        </CardContent>
      </Card>
      {run.summary ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Score title="Candidate" score={run.summary.candidate} />
          <Score title="Live version" score={run.summary.baseline} />
        </div>
      ) : null}
      {byCase.size > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Cases</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Case</TableHead>
                  <TableHead>{version(run.candidate_id)}</TableHead>
                  <TableHead>{version(run.baseline_id)}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...byCase.entries()].map(([key, versions]) => (
                  <TableRow key={key}>
                    <TableCell className="font-mono text-xs">{key}</TableCell>
                    {[run.candidate_id, run.baseline_id].map((id) => {
                      const item = versions[id]
                      return (
                        <TableCell
                          key={id}
                          className={cn(
                            "text-xs",
                            item?.passed
                              ? "text-emerald-700 dark:text-emerald-300"
                              : "text-muted-foreground"
                          )}
                        >
                          {item
                            ? `${item.passed ? "passed" : "failed"}, ${usd(item.cost_usd)}`
                            : "-"}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

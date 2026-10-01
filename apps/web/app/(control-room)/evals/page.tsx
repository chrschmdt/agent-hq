import type { Metadata } from "next"
import Link from "next/link"

import { isAdmin } from "@/auth"
import { EvalStatusBadge } from "@/components/evals/eval-status"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
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
import { CACHED, cachedRead } from "@/lib/api/cached"
import { serverApi } from "@/lib/api/server"
import { moment, usd, version } from "@/lib/format"

export const metadata: Metadata = { title: "Evals" }
export const dynamic = "force-dynamic"

const WHERE = {
  github: "in GitHub Actions",
  inprocess: "in the api's own queue",
  cli: "from the command line",
}

async function evals() {
  const [runs, settings] = await Promise.all([
    serverApi.GET("/api/evals").catch(() => null),
    serverApi.GET("/api/evals/settings").catch(() => null),
  ])
  return runs?.data
    ? { runs: { data: runs.data }, settings: { data: settings?.data } }
    : undefined
}

export default async function EvalsPage() {
  const shown = (await isAdmin())
    ? await evals()
    : await cachedRead(CACHED.evals, "evals", 300, evals).catch(() => undefined)
  const runs = shown?.runs
  const settings = shown?.settings
  return (
    <>
      <PageHeader
        title="Evals"
        description="The eval gate: a candidate version against the live one on the same cases, before it may take a canary."
      />
      {!runs?.data ? (
        <ApiOffline />
      ) : (
        <>
          {settings?.data ? (
            <Card>
              <CardHeader>
                <CardTitle>How the gate runs here</CardTitle>
                <CardDescription>
                  Runs start {WHERE[settings.data.backend]}, from a
                  version&apos;s page. Each agent has its suite: τ³ tasks for
                  Support, labeled routing cases for the Dispatcher, a
                  carrier-delay day for Ops and Insights.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                {Object.entries(settings.data.suites).map(([agent, params]) => (
                  <span key={agent}>
                    <span className="capitalize">{agent}</span>:{" "}
                    <span className="text-muted-foreground">
                      {params.suite}, {params.cases} cases x {params.trials} on{" "}
                      {params.profile}
                    </span>
                  </span>
                ))}
              </CardContent>
            </Card>
          ) : null}
          <Card>
            <CardContent>
              {runs.data.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  No gate runs yet. Draft a version on an agent&apos;s page,
                  then run the gate on it.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Candidate</TableHead>
                      <TableHead>Against</TableHead>
                      <TableHead>Suite</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Scores</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                      <TableHead>Requested</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {runs.data.map((run) => (
                      <TableRow key={run.eval_run_id}>
                        <TableCell className="font-mono text-xs">
                          <Link
                            href={`/evals/${run.eval_run_id}`}
                            className="underline underline-offset-4"
                          >
                            {version(run.candidate_id)}
                          </Link>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {version(run.baseline_id)}
                        </TableCell>
                        <TableCell>
                          {run.params.suite}, {run.params.profile}
                        </TableCell>
                        <TableCell>
                          <EvalStatusBadge status={run.status} />
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {run.summary
                            ? `${run.summary.candidate.score} vs ${run.summary.baseline.score}`
                            : "-"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {usd(run.cost_usd)}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {moment(run.created_at)} by {run.requested_by}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </>
  )
}

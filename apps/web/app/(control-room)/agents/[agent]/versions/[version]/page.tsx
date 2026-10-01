import type { Metadata } from "next"
import Link from "next/link"
import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"
import { EvalStatusBadge } from "@/components/evals/eval-status"
import { PageHeader } from "@/components/shell/page-header"
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
import { PromptDiff } from "@/components/versions/prompt-diff"
import { VersionStatusBadge } from "@/components/versions/version-status"
import { CACHED, cachedRead } from "@/lib/api/cached"
import { serverApi } from "@/lib/api/server"
import { moment, usd, words, version as versionName } from "@/lib/format"

export const metadata: Metadata = { title: "Version" }
export const dynamic = "force-dynamic"

function Fact({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  )
}

async function version(agent: string, versionId: string, against?: string) {
  const found = await serverApi.GET("/api/versions/{version_id}", {
    params: { path: { version_id: versionId } },
  })
  const v = found.data
  if (!v || v.agent !== agent) {
    return undefined
  }
  const [all, evals] = await Promise.all([
    serverApi.GET("/api/versions", { params: { query: { agent } } }),
    serverApi.GET("/api/evals", { params: { query: { agent } } }),
  ])
  const base = against ?? v.parent_id ?? undefined
  const diff =
    base && base !== v.version_id
      ? await serverApi.GET("/api/versions/{version_id}/diff", {
          params: {
            path: { version_id: v.version_id },
            query: { against: base },
          },
        })
      : null
  return {
    v,
    all: all.data ?? [],
    runs: evals.data ?? [],
    diff: diff?.data ?? null,
  }
}

export default async function VersionPage({
  params,
  searchParams,
}: {
  params: Promise<{ agent: string; version: string }>
  searchParams: Promise<{ against?: string }>
}) {
  const { agent, version: segment } = await params
  const versionId = decodeURIComponent(segment)
  const { against } = await searchParams
  const load = () => version(agent, versionId, against)
  const shown = (await isAdmin())
    ? await load()
    : await cachedRead(
        CACHED.versions,
        `version:${versionId}:${against ?? ""}`,
        300,
        load
      ).catch(() => undefined)
  if (!shown) {
    notFound()
  }
  const { v, all, runs, diff } = shown
  const live = all.find((other) => other.status === "live")
  const gates = runs.filter((run) => run.candidate_id === v.version_id)
  const config = v.config
  return (
    <>
      <PageHeader title={versionName(v.version_id)} description={v.note}>
        <VersionStatusBadge status={v.status} pct={v.canary_pct} />
        <Link
          href={`/agents/${agent}`}
          className="text-sm underline underline-offset-4"
        >
          All versions of {agent}
        </Link>
      </PageHeader>
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>
                Changes against{" "}
                <span className="font-mono">{diff?.before ?? "nothing"}</span>
              </CardTitle>
              <CardDescription className="flex flex-wrap gap-3">
                {v.parent_id ? (
                  <Link
                    href={`?against=${v.parent_id}`}
                    className="underline underline-offset-4"
                  >
                    against its parent, {v.parent_id}
                  </Link>
                ) : null}
                {live && live.version_id !== v.version_id ? (
                  <Link
                    href={`?against=${live.version_id}`}
                    className="underline underline-offset-4"
                  >
                    against the live version, {versionName(live.version_id)}
                  </Link>
                ) : null}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {!diff ? (
                <p className="text-sm text-muted-foreground">
                  The first version of {agent}, seeded from code.
                </p>
              ) : (
                <>
                  {diff.changes.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Setting</TableHead>
                          <TableHead>Before</TableHead>
                          <TableHead>After</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {diff.changes.map((change) => (
                          <TableRow key={change.field}>
                            <TableCell>{words(change.field)}</TableCell>
                            <TableCell className="max-w-xs font-mono text-xs whitespace-normal">
                              {JSON.stringify(change.before)}
                            </TableCell>
                            <TableCell className="max-w-xs font-mono text-xs whitespace-normal">
                              {JSON.stringify(change.after)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : null}
                  <PromptDiff lines={diff.prompt} />
                </>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Eval gate runs</CardTitle>
              <CardDescription>
                This version against the live version of its time, on the same
                cases.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              {gates.length === 0 ? (
                <p className="text-muted-foreground">Not gated yet.</p>
              ) : (
                gates.map((run) => (
                  <Link
                    key={run.eval_run_id}
                    href={`/evals/${run.eval_run_id}`}
                    className="flex flex-wrap items-center justify-between gap-2"
                  >
                    <span className="underline underline-offset-4">
                      {run.params.suite} against {run.baseline_id},{" "}
                      {moment(run.created_at)}
                    </span>
                    <EvalStatusBadge status={run.status} />
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Prompt</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="max-h-[32rem] overflow-auto font-mono text-xs whitespace-pre-wrap">
                {config.prompt_stable}
                {"\n\n"}
                {config.prompt_context}
              </pre>
            </CardContent>
          </Card>
        </div>
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Configuration</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <Fact label="Model">{config.model ?? "the profile's"}</Fact>
              <Fact label="Model calls per turn">{config.max_model_calls}</Fact>
              <Fact label="Spend per work item">{usd(config.max_usd)}</Fact>
              <div className="flex flex-wrap gap-1 pt-1">
                {config.tools.map((tool) => (
                  <Badge key={tool} variant="secondary" className="font-mono">
                    {tool}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Lifecycle</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <Fact label="Created">
                {moment(v.created_at)} by {v.created_by}
              </Fact>
              <Fact label="Status since">{moment(v.status_at)}</Fact>
              {v.status_reason ? (
                <Fact label="Why">{v.status_reason}</Fact>
              ) : null}
              <Fact label="Digest">
                <span className="font-mono text-xs">
                  {v.digest.slice(0, 12)}
                </span>
              </Fact>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

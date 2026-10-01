import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"
import { EvalView } from "@/components/evals/eval-view"
import { PageHeader } from "@/components/shell/page-header"
import { CACHED, cachedRead } from "@/lib/api/cached"
import { serverApi } from "@/lib/api/server"
import { version } from "@/lib/format"

export const metadata: Metadata = { title: "Eval run" }
export const dynamic = "force-dynamic"

async function evalRun(id: string) {
  const path = { params: { path: { eval_run_id: id } } }
  const [run, cases] = await Promise.all([
    serverApi.GET("/api/evals/{eval_run_id}", path),
    serverApi.GET("/api/evals/{eval_run_id}/cases", path),
  ])
  return run.data ? { run: run.data, cases: cases.data ?? [] } : undefined
}

export default async function EvalRunPage({
  params,
}: {
  params: Promise<{ evalRunId: string }>
}) {
  const { evalRunId } = await params
  const admin = await isAdmin()
  const load = () => evalRun(evalRunId)
  const shown = admin
    ? await load()
    : await cachedRead(CACHED.evals, `eval:${evalRunId}`, 300, load).catch(
        () => undefined
      )
  if (!shown) {
    notFound()
  }
  return (
    <>
      <PageHeader
        title={`Eval gate for ${version(shown.run.candidate_id)}`}
        description={`Against ${version(shown.run.baseline_id)}, the live version when it was requested.`}
      />
      <EvalView initial={shown} live={admin} />
    </>
  )
}

import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"
import { RunScreen } from "@/components/runs/run-screen"
import { PageHeader } from "@/components/shell/page-header"
import { CACHED, cachedRead } from "@/lib/api/cached"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Run" }
export const dynamic = "force-dynamic"

async function live(runId: string) {
  const path = { params: { path: { work_item_id: runId } } }
  const [run, thread, agents] = await Promise.all([
    serverApi.GET("/api/runs/{work_item_id}", path),
    serverApi.GET("/api/runs/{work_item_id}/thread", path),
    serverApi.GET("/api/agents"),
  ])
  return run.data
    ? { run: run.data, thread: thread.data ?? null, agents: agents.data ?? [] }
    : null
}

export default async function RunPage({
  params,
}: {
  params: Promise<{ runId: string }>
}) {
  const { runId } = await params
  const graph = await cachedRead(CACHED.graph, "graph", 86_400, async () => {
    const { data } = await serverApi.GET("/api/graph")
    return data
  }).catch(() => undefined)
  if (!graph) {
    notFound()
  }
  const admin = await isAdmin()
  return (
    <>
      <PageHeader
        title="Run"
        description="One piece of work, step by step: the route it took, the agent's loop, and every call it made."
      />
      <RunScreen
        runId={runId}
        topology={graph.team}
        live={admin ? await live(runId) : null}
      />
    </>
  )
}

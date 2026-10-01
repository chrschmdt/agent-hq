import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"
import { AgentScreen, type LiveAgent } from "@/components/agents/agent-screen"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Agent" }
export const dynamic = "force-dynamic"

const AGENTS = new Set(["dispatcher", "support", "ops", "insights"])

async function live(name: string): Promise<LiveAgent | null> {
  const agent = await serverApi.GET("/api/agents/{name}", {
    params: { path: { name } },
  })
  if (!agent.data) {
    return null
  }
  const [versions, scorecards, version] = await Promise.all([
    serverApi.GET("/api/versions", { params: { query: { agent: name } } }),
    serverApi.GET("/api/agents/{agent}/scorecards", {
      params: { path: { agent: name } },
    }),
    serverApi.GET("/api/versions/{version_id}", {
      params: { path: { version_id: agent.data.version } },
    }),
  ])
  return {
    agent: agent.data,
    versions: versions.data ?? [],
    scorecards: scorecards.data ?? null,
    config: version.data?.config ?? null,
  }
}

export default async function AgentPage({
  params,
}: {
  params: Promise<{ agent: string }>
}) {
  const { agent: name } = await params
  if (!AGENTS.has(name)) {
    notFound()
  }
  return (
    <AgentScreen
      name={name}
      live={(await isAdmin()) ? await live(name) : null}
    />
  )
}

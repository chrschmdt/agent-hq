import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { AgentsGrid } from "@/components/agents/agents-grid"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Agents" }
export const dynamic = "force-dynamic"

export default async function AgentsPage() {
  const admin = await isAdmin()
  const agents = admin
    ? await serverApi.GET("/api/agents").catch(() => null)
    : null
  return (
    <>
      <PageHeader
        title="Agents"
        description="The team: what each agent may do, the model it runs on, and its workload."
      />
      {admin && !agents?.data ? (
        <ApiOffline />
      ) : (
        <AgentsGrid live={agents?.data ?? null} />
      )}
    </>
  )
}

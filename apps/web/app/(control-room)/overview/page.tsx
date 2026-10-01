import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { LiveFeed } from "@/components/feed/live-feed"
import { MapPanel } from "@/components/map/map-panel"
import { KpiRow } from "@/components/overview/kpi-row"
import { SimClock } from "@/components/overview/sim-clock"
import { StatusBar } from "@/components/overview/status-bar"
import { ValuePanel } from "@/components/overview/value-panel"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { serverApi } from "@/lib/api/server"
import type { KpiPoint } from "@/lib/api/types"
import { KPIS } from "@/lib/kpis"

export const metadata: Metadata = { title: "Overview" }
export const dynamic = "force-dynamic"

async function live() {
  try {
    const [status, agents, sim, value, ...kpis] = await Promise.all([
      serverApi.GET("/api/status"),
      serverApi.GET("/api/agents"),
      serverApi.GET("/api/sim"),
      serverApi.GET("/api/value"),
      ...KPIS.map(({ metric }) =>
        serverApi.GET("/api/kpis", { params: { query: { metric, days: 30 } } })
      ),
    ])
    if (!status.data || !agents.data || !sim.data || !value.data) {
      return null
    }
    return {
      status: status.data,
      agents: agents.data,
      sim: sim.data,
      value: value.data,
      kpis: kpis.map((result) => (result.data ?? []) as KpiPoint[]),
    }
  } catch {
    return null
  }
}

export default async function OverviewPage() {
  const admin = await isAdmin()
  const data = admin ? await live() : null
  return (
    <>
      <PageHeader
        title="Overview"
        description="AI agents run customer operations for an online store, and a person manages them from here."
      />
      {admin && !data ? (
        <ApiOffline />
      ) : (
        <>
          <MapPanel initialAgents={data?.agents ?? []} />
          <StatusBar initial={data?.status ?? null} />
          <section className="grid gap-4 lg:grid-cols-[1fr_18rem]">
            <ValuePanel initial={data?.value ?? null} />
            <SimClock initial={data?.sim ?? null} />
          </section>
          <KpiRow initial={data?.kpis ?? null} />
          <LiveFeed />
        </>
      )}
    </>
  )
}

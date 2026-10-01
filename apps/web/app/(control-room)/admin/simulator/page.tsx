import type { Metadata } from "next"

import { LiveFeed } from "@/components/feed/live-feed"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { SimControls } from "@/components/sim/sim-controls"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Simulator" }
export const dynamic = "force-dynamic"

export default async function SimulatorPage() {
  const sim = await serverApi.GET("/api/sim").catch(() => null)
  return (
    <>
      <PageHeader
        title="Simulator"
        description="Play a day at the store in fast time: customers write in, parcels arrive, and things go wrong."
      />
      {sim?.data ? (
        <>
          <SimControls initial={sim.data} />
          <LiveFeed liveOnly />
        </>
      ) : (
        <ApiOffline />
      )}
    </>
  )
}

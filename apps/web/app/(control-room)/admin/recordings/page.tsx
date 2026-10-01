import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"
import { RecordingsAdmin } from "@/components/admin/recordings-admin"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { operatorApi } from "@/lib/api/operator"

export const metadata: Metadata = { title: "Recordings" }
export const dynamic = "force-dynamic"

export default async function RecordingsPage() {
  if (!(await isAdmin())) {
    notFound()
  }
  const [days, recordings] = await Promise.all([
    operatorApi.GET("/api/sim/runs").catch(() => null),
    operatorApi.GET("/api/recordings").catch(() => null),
  ])
  return (
    <>
      <PageHeader
        title="Recordings"
        description="Record a finished simulated day, and choose which recorded days visitors can watch."
      />
      {days?.data && recordings?.data ? (
        <RecordingsAdmin days={days.data} recordings={recordings.data} />
      ) : (
        <ApiOffline />
      )}
    </>
  )
}

import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { ApiOffline } from "@/components/shell/api-offline"
import { OpenInDrawer } from "@/components/shell/drawer-context"
import { PageHeader } from "@/components/shell/page-header"
import { IncidentsList } from "@/components/team/incidents-list"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Incidents" }
export const dynamic = "force-dynamic"

export default async function IncidentsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { open } = await searchParams
  const admin = await isAdmin()
  const incidents = admin
    ? await serverApi.GET("/api/incidents").catch(() => null)
    : null
  return (
    <>
      <PageHeader
        title="Incidents"
        description="Problems the Ops analyst found and confirmed with data, newest first."
      />
      {admin && !incidents?.data ? (
        <ApiOffline />
      ) : (
        <IncidentsList live={incidents?.data ?? null} />
      )}
      {typeof open === "string" ? (
        <OpenInDrawer target={{ kind: "incident", id: open }} />
      ) : null}
    </>
  )
}

import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { WorkBoard } from "@/components/work/work-board"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Work" }
export const dynamic = "force-dynamic"

export default async function WorkPage() {
  const admin = await isAdmin()
  const work = admin
    ? await serverApi
        .GET("/api/work", { params: { query: { limit: 300 } } })
        .catch(() => null)
    : null
  return (
    <>
      <PageHeader
        title="Work"
        description="Every ticket, alert and flag, by where it stands. Open one to see its run."
      />
      {admin && !work?.data ? (
        <ApiOffline />
      ) : (
        <WorkBoard initial={work?.data ?? null} />
      )}
    </>
  )
}

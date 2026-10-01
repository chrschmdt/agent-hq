import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { ApprovalsList } from "@/components/approvals/approvals-list"
import { ApiOffline } from "@/components/shell/api-offline"
import { OpenInDrawer } from "@/components/shell/drawer-context"
import { PageHeader } from "@/components/shell/page-header"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Approvals" }
export const dynamic = "force-dynamic"

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { open } = await searchParams
  const admin = await isAdmin()
  const approvals = admin
    ? await serverApi.GET("/api/approvals").catch(() => null)
    : null
  return (
    <>
      <PageHeader
        title="Approvals"
        description="Actions an agent paused for, oldest first. The agent resumes when a person decides."
      />
      {admin && !approvals?.data ? (
        <ApiOffline />
      ) : (
        <ApprovalsList live={approvals?.data ?? null} />
      )}
      {typeof open === "string" ? (
        <OpenInDrawer target={{ kind: "approval", id: open }} />
      ) : null}
    </>
  )
}

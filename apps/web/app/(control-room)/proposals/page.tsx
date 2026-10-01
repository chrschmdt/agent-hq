import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { ApiOffline } from "@/components/shell/api-offline"
import { OpenInDrawer } from "@/components/shell/drawer-context"
import { PageHeader } from "@/components/shell/page-header"
import { ProposalsList } from "@/components/team/proposals-list"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Proposals" }
export const dynamic = "force-dynamic"

export default async function ProposalsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { open } = await searchParams
  const admin = await isAdmin()
  const proposals = admin
    ? await serverApi.GET("/api/proposals").catch(() => null)
    : null
  return (
    <>
      <PageHeader
        title="Proposals"
        description="Changes Insights proposes, for a person to approve. An approved article goes live in the knowledge base."
      />
      {admin && !proposals?.data ? (
        <ApiOffline />
      ) : (
        <ProposalsList live={proposals?.data ?? null} />
      )}
      {typeof open === "string" ? (
        <OpenInDrawer target={{ kind: "proposal", id: open }} />
      ) : null}
    </>
  )
}

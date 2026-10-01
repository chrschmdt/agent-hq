import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"
import { SpendAdmin } from "@/components/admin/spend-admin"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { operatorApi } from "@/lib/api/operator"

export const metadata: Metadata = { title: "Spend and limits" }
export const dynamic = "force-dynamic"

export default async function SpendPage() {
  if (!(await isAdmin())) {
    notFound()
  }
  const limits = await operatorApi.GET("/api/limits").catch(() => null)
  return (
    <>
      <PageHeader
        title="Spend and limits"
        description="What the agents spent today against their budgets, their kill switches, and the models' breakers."
      />
      {limits?.data ? <SpendAdmin limits={limits.data} /> : <ApiOffline />}
    </>
  )
}

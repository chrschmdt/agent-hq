import type { Metadata } from "next"

import { ModelsAdmin } from "@/components/admin/models-admin"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Models" }
export const dynamic = "force-dynamic"

export default async function ModelsPage() {
  const view = await serverApi.GET("/api/models").catch(() => null)
  return (
    <>
      <PageHeader
        title="Models"
        description="Which models play each role: four profiles, from rule-based stand-ins to Opus 5.5. The switch applies to every role at once."
      />
      {view?.data ? <ModelsAdmin view={view.data} /> : <ApiOffline />}
    </>
  )
}

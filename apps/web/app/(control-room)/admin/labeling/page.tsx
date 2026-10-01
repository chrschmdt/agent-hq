import type { Metadata } from "next"

import { Labeler } from "@/components/quality/labeler"
import { PageHeader } from "@/components/shell/page-header"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Labeling" }
export const dynamic = "force-dynamic"

export default async function LabelingPage() {
  const queue = await serverApi
    .GET("/api/qa/queue", { params: { query: { limit: 1 } } })
    .catch(() => null)
  return (
    <>
      <PageHeader
        title="Labeling"
        description="Label reviewed runs blind, criterion by criterion. The reviewer's verdicts count on the scorecards once labels like these show it agrees with people."
      />
      <Labeler initial={queue?.data?.[0] ?? null} />
    </>
  )
}

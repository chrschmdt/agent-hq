import type { Metadata } from "next"

import { isAdmin } from "@/auth"
import { QualityScreen } from "@/components/quality/quality-screen"
import { ApiOffline } from "@/components/shell/api-offline"
import { PageHeader } from "@/components/shell/page-header"
import { CACHED, cachedRead } from "@/lib/api/cached"
import { serverApi } from "@/lib/api/server"

export const metadata: Metadata = { title: "Quality" }
export const dynamic = "force-dynamic"

async function live() {
  const [reviews, guardrails] = await Promise.all([
    serverApi.GET("/api/qa/reviews", { params: { query: { limit: 100 } } }),
    serverApi.GET("/api/guardrails"),
  ])
  return reviews.data && guardrails.data
    ? { reviews: reviews.data, guardrails: guardrails.data }
    : null
}

export default async function QualityPage() {
  const admin = await isAdmin()
  const calibrate = async () =>
    (await serverApi.GET("/api/qa/calibration").catch(() => null))?.data
  const [shown, calibration] = await Promise.all([
    admin ? live().catch(() => null) : Promise.resolve(null),
    admin
      ? calibrate()
      : cachedRead(CACHED.calibration, "calibration", 600, calibrate).catch(
          () => undefined
        ),
  ])
  return (
    <>
      <PageHeader
        title="Quality"
        description="The QA reviewer grades finished runs against each agent's rubric. Its verdicts count once people's labels show it can be trusted. The guardrails show what they blocked."
      />
      {admin && !shown ? (
        <ApiOffline />
      ) : (
        <QualityScreen live={shown} calibration={calibration ?? []} />
      )}
    </>
  )
}

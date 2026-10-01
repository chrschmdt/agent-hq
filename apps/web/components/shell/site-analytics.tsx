"use client"

import { Analytics } from "@vercel/analytics/next"
import { SpeedInsights } from "@vercel/speed-insights/next"

import { isAdminPage } from "@/lib/site"

export function SiteAnalytics() {
  return (
    <>
      <Analytics
        beforeSend={(event) => (isAdminPage(event.url) ? null : event)}
      />
      <SpeedInsights
        beforeSend={(event) => (isAdminPage(event.url) ? null : event)}
      />
    </>
  )
}

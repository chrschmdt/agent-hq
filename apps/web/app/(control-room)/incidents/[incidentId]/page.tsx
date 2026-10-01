import { redirect } from "next/navigation"

import { detailHref } from "@/lib/drawer"

export default async function IncidentPage({
  params,
}: {
  params: Promise<{ incidentId: string }>
}) {
  const { incidentId } = await params
  redirect(detailHref({ kind: "incident", id: incidentId }))
}

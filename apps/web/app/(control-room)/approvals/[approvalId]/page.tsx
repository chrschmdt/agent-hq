import { redirect } from "next/navigation"

import { detailHref } from "@/lib/drawer"

export default async function ApprovalPage({
  params,
}: {
  params: Promise<{ approvalId: string }>
}) {
  const { approvalId } = await params
  redirect(detailHref({ kind: "approval", id: approvalId }))
}

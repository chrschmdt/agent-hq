import { redirect } from "next/navigation"

import { detailHref } from "@/lib/drawer"

export default async function ProposalPage({
  params,
}: {
  params: Promise<{ proposalId: string }>
}) {
  const { proposalId } = await params
  redirect(detailHref({ kind: "proposal", id: proposalId }))
}

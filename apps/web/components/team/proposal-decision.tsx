"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import { decideProposal } from "@/app/actions"
import { useCanAct } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

export function ProposalDecision({
  proposalId,
  hasDraft,
}: {
  proposalId: string
  hasDraft: boolean
}) {
  const admin = useCanAct()
  const router = useRouter()
  const client = useQueryClient()
  const [note, setNote] = useState("")
  const [pending, startTransition] = useTransition()
  const decide = (verdict: "approved" | "rejected") =>
    startTransition(async () => {
      const result = await decideProposal(
        proposalId,
        verdict,
        note.trim() || null
      )
      if (result.ok) {
        toast.success(
          verdict === "approved" && hasDraft
            ? "Approved, and the article is published."
            : `Proposal ${verdict}.`
        )
        router.refresh()
        await Promise.all([
          client.invalidateQueries({ queryKey: ["proposals"] }),
          client.invalidateQueries({ queryKey: ["runs"] }),
        ])
      } else {
        toast.error(result.error)
      }
    })
  if (!admin) {
    return (
      <p className="text-sm text-muted-foreground">
        Sign in as the admin to decide.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      <Textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="A note, optional"
      />
      <div className="flex justify-end gap-2">
        <Button
          variant="destructive"
          onClick={() => decide("rejected")}
          disabled={pending}
        >
          Reject
        </Button>
        <Button onClick={() => decide("approved")} disabled={pending}>
          {hasDraft ? "Approve and publish" : "Approve"}
        </Button>
      </div>
    </div>
  )
}

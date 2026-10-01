"use client"

import { Ago } from "@/components/ago"
import { RecordingNotice } from "@/components/recording/recording-notice"
import { useRecorded } from "@/components/recording/recording-provider"
import { DrawerLink } from "@/components/shell/drawer-context"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { Approval } from "@/lib/api/types"
import { sentence, usd, words } from "@/lib/format"
import { approvalsAt, decidedAt } from "@/lib/recording/derive"

function ApprovalRow({ approval }: { approval: Approval }) {
  return (
    <DrawerLink
      target={{ kind: "approval", id: approval.id }}
      className="block"
    >
      <Card className="transition-colors hover:bg-muted/40">
        <CardContent className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span className="font-medium">
              {sentence(approval.request.action)}
            </span>
            <span className="text-sm text-muted-foreground">
              {approval.request.reason}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {approval.status !== "pending" ? (
              <Badge variant="secondary">{words(approval.status)}</Badge>
            ) : null}
            {approval.request.cost_usd ? (
              <Badge variant="outline" className="tabular-nums">
                {usd(approval.request.cost_usd)}
              </Badge>
            ) : null}
            <Ago iso={approval.decided_at ?? approval.created_at} />
          </div>
        </CardContent>
      </Card>
    </DrawerLink>
  )
}

export function ApprovalsList({ live }: { live: Approval[] | null }) {
  const recorded = useRecorded((prepared, cursor) => ({
    waiting: approvalsAt(prepared, cursor),
    decided: decidedAt(prepared, cursor),
  }))
  const waiting = recorded.recording ? recorded.data?.waiting : live
  const decided = recorded.recording ? (recorded.data?.decided ?? []) : []
  if (!waiting) {
    return <RecordingNotice />
  }
  return (
    <div className="flex flex-col gap-3">
      {waiting.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Nothing waits for a person</CardTitle>
            <CardDescription>
              Refunds over the limit and every goodwill refund pause here until
              someone decides.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        waiting.map((approval) => (
          <ApprovalRow key={approval.id} approval={approval} />
        ))
      )}
      {decided.length > 0 ? (
        <>
          <h2 className="mt-3 text-sm font-medium text-muted-foreground">
            Decided
          </h2>
          {decided.map((approval) => (
            <ApprovalRow key={approval.id} approval={approval} />
          ))}
        </>
      ) : null}
    </div>
  )
}

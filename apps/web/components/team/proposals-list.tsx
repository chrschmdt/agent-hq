"use client"

import { RecordingNotice } from "@/components/recording/recording-notice"
import { useDay, useRecorded } from "@/components/recording/recording-provider"
import { DrawerLink } from "@/components/shell/drawer-context"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { ProposalRecord } from "@/lib/api/types"
import { moment, words } from "@/lib/format"
import { proposalsAt } from "@/lib/recording/derive"

export function ProposalsList({ live }: { live: ProposalRecord[] | null }) {
  const day = useDay()
  const recorded = useRecorded(proposalsAt)
  const all = recorded.recording ? recorded.data : live
  if (!all) {
    return <RecordingNotice />
  }
  const pending = all.filter((p) => p.status === "pending")
  const decided = all.filter((p) => p.status !== "pending")
  return (
    <>
      {all.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No proposals yet</CardTitle>
            <CardDescription>
              Insights proposes fixes after the Ops analyst hands it an
              incident.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        [
          { title: "To review", items: pending },
          { title: "Decided", items: decided },
        ].map((group) =>
          group.items.length === 0 ? null : (
            <section key={group.title} className="flex flex-col gap-3">
              <h2 className="text-sm font-medium text-muted-foreground">
                {group.title}
              </h2>
              {group.items.map((record) => (
                <DrawerLink
                  key={record.proposal_id}
                  target={{ kind: "proposal", id: record.proposal_id }}
                  className="block"
                >
                  <Card className="transition-colors hover:bg-muted/40">
                    <CardContent className="flex flex-col gap-1.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">
                          {record.proposal.title}
                        </span>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">
                            {words(record.proposal.kind)}
                          </Badge>
                          {record.proposal.draft_id ? (
                            <Badge variant="outline">draft article</Badge>
                          ) : null}
                          <span className="text-xs text-muted-foreground">
                            {moment(day(record.created_at))}
                          </span>
                        </div>
                      </div>
                      <p className="line-clamp-2 text-sm text-muted-foreground">
                        {record.proposal.problem}
                      </p>
                    </CardContent>
                  </Card>
                </DrawerLink>
              ))}
            </section>
          )
        )
      )}
    </>
  )
}

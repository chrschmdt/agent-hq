"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import {
  useDay,
  useRecorded,
  useSource,
} from "@/components/recording/recording-provider"
import {
  DrawerBody,
  DrawerHeader,
  DrawerLink,
  DrawerPending,
} from "@/components/shell/drawer-context"
import { Article } from "@/components/team/article"
import { ProposalDecision } from "@/components/team/proposal-decision"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { api } from "@/lib/api/client"
import { moment, words } from "@/lib/format"
import { draftAt, proposalAt } from "@/lib/recording/derive"

function useLiveProposal(proposalId: string, enabled: boolean) {
  const record = useQuery({
    queryKey: ["proposals", proposalId],
    queryFn: async () =>
      (
        await api.GET("/api/proposals/{proposal_id}", {
          params: { path: { proposal_id: proposalId } },
        })
      ).data ?? null,
    enabled,
  })
  const draftId = record.data?.proposal.draft_id ?? undefined
  const draft = useQuery({
    queryKey: ["proposals", proposalId, "draft", draftId],
    queryFn: async () =>
      (
        await api.GET("/api/drafts/{draft_id}", {
          params: { path: { draft_id: draftId ?? "" } },
        })
      ).data ?? null,
    enabled: enabled && draftId !== undefined,
  })
  const shown = record.data
    ? { record: record.data, draft: draft.data ?? null }
    : null
  return { shown, isPending: record.isPending, isError: record.isError }
}

export function ProposalPanel({ proposalId }: { proposalId: string }) {
  const day = useDay()
  const { mode } = useSource()
  const recorded = useRecorded((prepared, cursor) => {
    const record = proposalAt(prepared, cursor, proposalId)
    const draftId = record?.proposal.draft_id
    return record
      ? {
          record,
          draft: draftId ? draftAt(prepared, cursor, draftId) : null,
        }
      : null
  })
  const live = useLiveProposal(proposalId, mode === "live")
  const shown = recorded.recording ? recorded.data : live.shown
  if (!shown) {
    return (
      <DrawerPending
        title="Proposal"
        id={proposalId}
        notYet="Insights has not made this proposal yet at this point of the recorded day."
        live={live}
      />
    )
  }
  const { record, draft } = shown
  const proposal = record.proposal
  const document = draft?.document as
    { body?: string; doc_id?: string; version?: number } | undefined
  return (
    <>
      <DrawerHeader
        title={proposal.title}
        description={`Proposed ${moment(day(record.created_at))}`}
      >
        <Badge variant="outline">{words(proposal.kind)}</Badge>
        <Badge variant={record.status === "pending" ? "default" : "outline"}>
          {record.status}
        </Badge>
      </DrawerHeader>
      <DrawerBody>
        <div className="grid gap-6 @3xl:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle>The proposal</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 text-sm">
                <p>
                  <span className="font-medium">Problem: </span>
                  {proposal.problem}
                </p>
                <p>
                  <span className="font-medium">Change: </span>
                  {proposal.proposal}
                </p>
                <p>
                  <span className="font-medium">Expected impact: </span>
                  {proposal.expected_impact}
                </p>
                <p>
                  <span className="font-medium">Risk: </span>
                  {proposal.risk}
                </p>
                <div>
                  <span className="font-medium">Evidence</span>
                  <ul className="list-disc pl-5 text-muted-foreground">
                    {proposal.evidence.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              </CardContent>
            </Card>
            {document?.body ? (
              <Card>
                <CardHeader>
                  <CardTitle>Draft article</CardTitle>
                  <CardDescription>
                    {document.doc_id}, version {document.version},{" "}
                    {draft?.status}. Agents cannot search it until it is
                    published.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Article markdown={document.body} />
                </CardContent>
              </Card>
            ) : null}
          </div>
          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Decision</CardTitle>
                <CardDescription>
                  {record.status === "pending"
                    ? recorded.recording
                      ? "Waiting for a person. Play on to see the decision."
                      : "Nothing changes until a person decides."
                    : `${record.status} by ${record.decided_by ?? "someone"}${record.note ? `: ${record.note}` : ""}`}
                </CardDescription>
              </CardHeader>
              {record.status === "pending" && !recorded.recording ? (
                <CardContent>
                  <ProposalDecision
                    proposalId={proposalId}
                    hasDraft={Boolean(proposal.draft_id)}
                  />
                </CardContent>
              ) : null}
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Where it came from</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                {record.incident_id ? (
                  <DrawerLink
                    target={{ kind: "incident", id: record.incident_id }}
                    className="underline underline-offset-4"
                  >
                    The incident
                  </DrawerLink>
                ) : null}
                <Link
                  href={`/runs/${record.work_item_id}`}
                  className="underline underline-offset-4"
                >
                  The run
                </Link>
              </CardContent>
            </Card>
          </div>
        </div>
      </DrawerBody>
    </>
  )
}

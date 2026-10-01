"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { DecisionPanel } from "@/components/approvals/decision-panel"
import {
  useDay,
  useRecorded,
  useSource,
} from "@/components/recording/recording-provider"
import { LinkedText, RecordLink } from "@/components/records/record-drawer"
import {
  DrawerBody,
  DrawerHeader,
  DrawerPending,
} from "@/components/shell/drawer-context"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { api } from "@/lib/api/client"
import type { Approval } from "@/lib/api/types"
import { moment, sentence, usd, words } from "@/lib/format"
import { approvalAt } from "@/lib/recording/derive"

async function fetchApproval(approvalId: string): Promise<Approval | null> {
  const { data } = await api.GET("/api/approvals/{approval_id}", {
    params: { path: { approval_id: approvalId } },
  })
  return data ?? null
}

export function ApprovalPanel({ approvalId }: { approvalId: string }) {
  const day = useDay()
  const { mode } = useSource()
  const recorded = useRecorded((prepared, cursor) => ({
    approval: approvalAt(prepared, cursor, approvalId),
  }))
  const live = useQuery({
    queryKey: ["approvals", approvalId],
    queryFn: () => fetchApproval(approvalId),
    enabled: mode === "live",
  })
  const approval = recorded.recording ? recorded.data?.approval : live.data
  const action = approval?.request.action
  const described = useQuery({
    queryKey: ["tool", action],
    queryFn: async () =>
      (
        await api.GET("/api/tools/{name}", {
          params: { path: { name: action ?? "" } },
        })
      ).data ?? null,
    enabled: action !== undefined,
    staleTime: Infinity,
  })
  const info = described.data ?? null
  if (!approval) {
    return (
      <DrawerPending
        title="Approval"
        id={approvalId}
        notYet="No agent has asked for this yet at this point of the recorded day."
        live={live}
      />
    )
  }
  const request = approval.request
  return (
    <>
      <DrawerHeader
        title={sentence(request.action)}
        description={request.reason}
      >
        <Badge variant="outline">{words(approval.status)}</Badge>
        {request.cost_usd ? (
          <Badge variant="outline" className="tabular-nums">
            {usd(request.cost_usd)}
          </Badge>
        ) : null}
      </DrawerHeader>
      <DrawerBody>
        <div className="grid gap-6 @3xl:grid-cols-[minmax(0,1fr)_20rem]">
          <DecisionPanel
            key={`${approval.status}:${info ? "tool" : "none"}`}
            approval={approval}
            tool={info}
          />
          <Card>
            <CardHeader>
              <CardTitle>Why it waits</CardTitle>
              <CardDescription>{info?.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              {request.cost_usd ? (
                <p>
                  Pays back{" "}
                  <span className="font-medium tabular-nums">
                    {usd(request.cost_usd)}
                  </span>
                  {info?.exception
                    ? ", as a goodwill exception to the policy."
                    : info?.refund_gated
                      ? ", over the approval limit."
                      : "."}
                </p>
              ) : null}
              {typeof request.arguments?.order_id === "string" ? (
                <p>
                  For order{" "}
                  <RecordLink
                    target={{ kind: "order", id: request.arguments.order_id }}
                  />
                </p>
              ) : null}
              <ul className="list-disc pl-5 text-muted-foreground">
                {(request.evidence ?? []).map((line) => (
                  <li key={line}>
                    <LinkedText text={line} />
                  </li>
                ))}
              </ul>
              <p className="text-muted-foreground">
                Requested {moment(day(approval.created_at))}.
              </p>
              <Link
                href={`/runs/${approval.work_item_id}`}
                className="underline underline-offset-4"
              >
                Open the run
              </Link>
            </CardContent>
          </Card>
        </div>
      </DrawerBody>
    </>
  )
}

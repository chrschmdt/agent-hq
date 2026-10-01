"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import {
  useDay,
  useRecorded,
  useSource,
} from "@/components/recording/recording-provider"
import { LinkedText, RecordLink } from "@/components/records/record-drawer"
import {
  DrawerBody,
  DrawerHeader,
  DrawerLink,
  DrawerPending,
} from "@/components/shell/drawer-context"
import { IncidentChain } from "@/components/team/incident-chain"
import { Severity } from "@/components/team/severity"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api } from "@/lib/api/client"
import type { AhqEvent, Incident, ProposalRecord } from "@/lib/api/types"
import { moment, words } from "@/lib/format"
import { incidentChain, LATER_KINDS } from "@/lib/inspector/chain"
import {
  eventsAt,
  incidentAt,
  proposalsAt,
  runAt,
} from "@/lib/recording/derive"

type Shown = {
  incident: Incident
  proposals: ProposalRecord[]
  later: AhqEvent[]
  runEvents: AhqEvent[]
}

function useLiveIncident(incidentId: string, enabled: boolean) {
  const incident = useQuery({
    queryKey: ["incidents", incidentId],
    queryFn: async () =>
      (
        await api.GET("/api/incidents/{incident_id}", {
          params: { path: { incident_id: incidentId } },
        })
      ).data ?? null,
    enabled,
  })
  const workItemId = incident.data?.work_item_id
  const run = useQuery({
    queryKey: ["runs", workItemId],
    queryFn: async () =>
      (
        await api.GET("/api/runs/{work_item_id}", {
          params: { path: { work_item_id: workItemId ?? "" } },
        })
      ).data ?? null,
    enabled: enabled && workItemId !== undefined,
  })
  const later = useQuery({
    queryKey: ["runs", "later"],
    queryFn: async () =>
      (
        await api.GET("/api/events/recent", {
          params: { query: { kind: [...LATER_KINDS], limit: 500 } },
        })
      ).data ?? [],
    enabled,
  })
  const proposals = useQuery({
    queryKey: ["proposals"],
    queryFn: async () => (await api.GET("/api/proposals")).data ?? [],
    enabled,
  })
  const shown: Shown | null = incident.data
    ? {
        incident: incident.data,
        proposals: proposals.data ?? [],
        later: later.data ?? [],
        runEvents: run.data?.events ?? [],
      }
    : null
  return { shown, isPending: incident.isPending, isError: incident.isError }
}

export function IncidentPanel({ incidentId }: { incidentId: string }) {
  const day = useDay()
  const { mode } = useSource()
  const recorded = useRecorded((prepared, cursor) => {
    const incident = incidentAt(prepared, cursor, incidentId)
    return incident
      ? {
          incident,
          proposals: proposalsAt(prepared, cursor),
          later: eventsAt(prepared, cursor, LATER_KINDS),
          runEvents:
            runAt(prepared, cursor, incident.work_item_id)?.run.events ?? [],
        }
      : null
  })
  const live = useLiveIncident(incidentId, mode === "live")
  const shown = recorded.recording ? recorded.data : live.shown
  if (!shown) {
    return (
      <DrawerPending
        title="Incident"
        id={incidentId}
        notYet="This incident has not been filed yet at this point of the recorded day."
        live={live}
      />
    )
  }
  const { incident, proposals } = shown
  const steps = incidentChain(shown.runEvents, shown.later, proposals)
  const first = [...shown.runEvents].sort((a, b) => a.id - b.id)[0]
  const origin = first ? Date.parse(first.recorded_at ?? first.occurred_at) : 0
  const report = incident.report
  const affected = Object.entries(report.affected).filter(
    ([key, value]) => key !== "order_ids" && value !== null
  )
  const linked = proposals.filter((p) => p.incident_id === incidentId)
  return (
    <>
      <DrawerHeader
        title={report.title}
        description={`Detected ${moment(day(incident.detected_at))}`}
      >
        <Severity level={report.severity} />
      </DrawerHeader>
      <DrawerBody>
        <div className="grid gap-6 @3xl:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="flex flex-col gap-6">
            <IncidentChain steps={steps} origin={origin} />
            <Card>
              <CardHeader>
                <CardTitle>What happened</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 text-sm">
                <p>{report.summary}</p>
                <p>
                  <span className="font-medium">Suspected cause: </span>
                  {report.suspected_cause}
                </p>
                <p>
                  <span className="font-medium">Recommended action: </span>
                  {report.recommended_action}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Evidence</CardTitle>
                <CardDescription>
                  The queries the analyst ran, and what they showed.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Query</TableHead>
                      <TableHead>Showed</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {report.evidence.map((item, index) => (
                      <TableRow key={index}>
                        <TableCell className="max-w-72 font-mono text-xs whitespace-pre-wrap">
                          {item.query}
                        </TableCell>
                        <TableCell className="text-sm whitespace-pre-wrap">
                          <LinkedText text={item.excerpt} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Affected</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                {affected.map(([key, value]) => (
                  <p key={key}>
                    <span className="text-muted-foreground">
                      {words(key)}:{" "}
                    </span>
                    {String(value)}
                  </p>
                ))}
                {report.affected.order_ids.length > 0 ? (
                  <p className="flex flex-wrap gap-x-2 gap-y-1 text-xs">
                    {report.affected.order_ids.map((orderId) => (
                      <RecordLink
                        key={orderId}
                        target={{ kind: "order", id: orderId }}
                      />
                    ))}
                  </p>
                ) : null}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Next</CardTitle>
                <CardDescription>{words(report.next)}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                {report.brief ? (
                  <p className="text-muted-foreground">{report.brief}</p>
                ) : null}
                {linked.map((proposal) => (
                  <DrawerLink
                    key={proposal.proposal_id}
                    target={{ kind: "proposal", id: proposal.proposal_id }}
                    className="underline underline-offset-4"
                  >
                    {proposal.proposal.title} ({proposal.status})
                  </DrawerLink>
                ))}
                <Link
                  href={`/runs/${incident.work_item_id}`}
                  className="underline underline-offset-4"
                >
                  Open the run
                </Link>
              </CardContent>
            </Card>
          </div>
        </div>
      </DrawerBody>
    </>
  )
}

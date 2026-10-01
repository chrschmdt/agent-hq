"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { toast } from "sonner"

import {
  type ActionResult,
  promoteVersion,
  requestGate,
  retireVersion,
  rollBackVersion,
  startCanary,
} from "@/app/actions"
import { Ago } from "@/components/ago"
import { useCanAct } from "@/components/shell/admin-context"
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
import { ActionDialog } from "@/components/versions/action-dialog"
import { VersionStatusBadge } from "@/components/versions/version-status"
import { api } from "@/lib/api/client"
import type { AgentVersion } from "@/lib/api/types"
import { STATUS_ORDER, versionActions } from "@/lib/management"
import { version as versionName } from "@/lib/format"

async function fetchVersions(agent: string): Promise<AgentVersion[]> {
  const { data } = await api.GET("/api/versions", {
    params: { query: { agent } },
  })
  return data ?? []
}

function gateResult(version: AgentVersion): string {
  const summary = version.eval_summary
  if (!summary) {
    return "not gated"
  }
  const candidate = summary.candidate as { score?: number; metric?: string }
  const baseline = summary.baseline as { score?: number }
  const verdict = summary.passed ? "passed" : "failed"
  return `${verdict}, ${candidate.metric ?? "score"} ${candidate.score ?? "-"} against ${baseline.score ?? "-"}`
}

export function VersionsPanel({
  agent,
  initial,
  recorded = false,
}: {
  agent: string
  initial: AgentVersion[]
  recorded?: boolean
}) {
  const admin = useCanAct()
  const client = useQueryClient()
  const { data: liveVersions } = useQuery({
    queryKey: ["versions", agent],
    queryFn: () => fetchVersions(agent),
    initialData: initial,
    enabled: !recorded,
  })
  const versions = recorded ? initial : liveVersions
  const sorted = [...versions].sort(
    (a, b) =>
      STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || b.number - a.number
  )
  const act = async (
    done: string,
    action: () => Promise<ActionResult<unknown>>
  ): Promise<boolean> => {
    const result = await action()
    if (!result.ok) {
      toast.error(result.error)
      return false
    }
    toast.success(done)
    await client.invalidateQueries({ queryKey: ["versions"] })
    await client.invalidateQueries({ queryKey: ["scorecards"] })
    await client.invalidateQueries({ queryKey: ["agents"] })
    return true
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Versions</CardTitle>
        <CardDescription>
          A change becomes a draft, passes the eval gate, takes a share of new
          work as a canary, and is promoted or rolled back on its scorecard.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Change</TableHead>
              <TableHead>Eval gate</TableHead>
              {admin ? <TableHead /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((version) => (
              <TableRow key={version.version_id}>
                <TableCell className="font-mono text-xs">
                  <Link
                    href={`/agents/${agent}/versions/${version.version_id}`}
                    className="underline underline-offset-4"
                  >
                    {versionName(version.version_id)}
                  </Link>
                </TableCell>
                <TableCell className="whitespace-normal">
                  <div className="flex flex-col gap-1">
                    <VersionStatusBadge
                      status={version.status}
                      pct={version.canary_pct}
                    />
                    <span className="text-xs text-muted-foreground">
                      <Ago iso={version.status_at} />
                    </span>
                  </div>
                </TableCell>
                <TableCell className="max-w-xs text-xs whitespace-normal">
                  <p>{version.note}</p>
                  {version.status_reason &&
                  version.status_reason !== version.note ? (
                    <p className="text-muted-foreground">
                      {version.status_reason}
                    </p>
                  ) : null}
                  <p className="text-muted-foreground">
                    by {version.created_by}
                  </p>
                </TableCell>
                <TableCell className="max-w-48 text-xs whitespace-normal text-muted-foreground">
                  {gateResult(version)}
                </TableCell>
                {admin ? (
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-1.5">
                      {versionActions(version.status).map((move) => (
                        <Move
                          key={move}
                          move={move}
                          version={version}
                          act={act}
                        />
                      ))}
                    </div>
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function Move({
  move,
  version,
  act,
}: {
  move: ReturnType<typeof versionActions>[number]
  version: AgentVersion
  act: (
    done: string,
    action: () => Promise<ActionResult<unknown>>
  ) => Promise<boolean>
}) {
  const id = version.version_id
  const name = versionName(id)
  const gated = version.status === "evaluated"
  switch (move) {
    case "gate":
      return (
        <ActionDialog
          label="Run eval gate"
          title={`Run the eval gate on ${name}`}
          description="Runs the agent's suite on this version and on the live version, on the same cases, and compares them. Outside the test profile this spends model credit."
          confirm="Run the gate"
          onConfirm={() =>
            act("The eval gate is running.", () => requestGate(id))
          }
        />
      )
    case "canary":
      return (
        <ActionDialog
          label="Start canary"
          title={`Put ${name} on a canary`}
          description={
            gated
              ? "The version takes this share of the agent's new work. Its scorecard is compared with the live version's after every finished run, and it is promoted or rolled back on its own."
              : "This version has not passed the eval gate. It can still take a share of new work if you say so, and the timeline records that it skipped the gate."
          }
          confirm="Start the canary"
          pct={20}
          flag={gated ? undefined : "Start without passing the eval gate"}
          onConfirm={({ pct, flag }) =>
            act(`${name} is on a canary.`, () => startCanary(id, pct, flag))
          }
        />
      )
    case "promote":
      return (
        <ActionDialog
          label="Promote"
          title={`Make ${name} live`}
          description={
            version.status === "canary"
              ? "The live version is retired and all new work goes to this one."
              : "This skips the canary: all new work goes to this version at once, and the timeline records that."
          }
          confirm="Promote"
          reason
          onConfirm={({ reason }) =>
            act(`${name} is live.`, () =>
              promoteVersion(id, reason, version.status !== "canary")
            )
          }
        />
      )
    case "rollback":
      return (
        <ActionDialog
          label="Roll back"
          title={`End the canary of ${name}`}
          description="All new work goes back to the live version. Work already pinned to the canary finishes on it."
          confirm="Roll back"
          reason
          destructive
          onConfirm={({ reason }) =>
            act(`${name} is rolled back.`, () => rollBackVersion(id, reason))
          }
        />
      )
    case "retire":
      return (
        <ActionDialog
          label="Retire"
          title={`Retire ${name}`}
          description="The version stays in the registry for the record but will not run."
          confirm="Retire"
          reason
          destructive
          onConfirm={({ reason }) =>
            act(`${name} is retired.`, () => retireVersion(id, reason))
          }
        />
      )
  }
}

"use client"

import { RecordingNotice } from "@/components/recording/recording-notice"
import { useRecorded } from "@/components/recording/recording-provider"
import { RunInspector } from "@/components/runs/run-inspector"
import { Card, CardContent } from "@/components/ui/card"
import type {
  AgentSummary,
  RunView,
  ThreadView,
  Topology,
} from "@/lib/api/types"
import { agentsAt, runAt } from "@/lib/recording/derive"

function Note({ children }: { children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="py-10 text-center text-sm text-muted-foreground">
        {children}
      </CardContent>
    </Card>
  )
}

export function RunScreen({
  runId,
  topology,
  live,
}: {
  runId: string
  topology: Topology
  live: {
    run: RunView
    thread: ThreadView | null
    agents: AgentSummary[]
  } | null
}) {
  const recorded = useRecorded((prepared, cursor) => ({
    known: prepared.runs.has(runId),
    view: runAt(prepared, cursor, runId),
    agents: agentsAt(prepared, cursor),
  }))
  if (recorded.recording) {
    if (!recorded.data) {
      return <RecordingNotice />
    }
    if (!recorded.data.known) {
      return <Note>This work item is not part of the recorded day.</Note>
    }
    if (!recorded.data.view) {
      return (
        <Note>
          This work item has not started yet at this point of the day. Play on,
          or move the scrubber later, to see it.
        </Note>
      )
    }
    return (
      <RunInspector
        key={runId}
        initial={recorded.data.view.run}
        initialThread={recorded.data.view.thread}
        topology={topology}
        agents={recorded.data.agents}
        replay
      />
    )
  }
  if (!live) {
    return <Note>There is no live run with this id.</Note>
  }
  return (
    <RunInspector
      key={runId}
      initial={live.run}
      initialThread={live.thread}
      topology={topology}
      agents={live.agents}
    />
  )
}

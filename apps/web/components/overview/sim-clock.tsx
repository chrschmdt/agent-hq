"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import {
  usePlayer,
  useRecorded,
} from "@/components/recording/recording-provider"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { api } from "@/lib/api/client"
import type { SimulatorState } from "@/lib/api/types"
import { moment, words } from "@/lib/format"
import { simAt } from "@/lib/recording/derive"
import { simulatedAt } from "@/lib/scene/frame"

const CLOCK_MS = 2000

export async function fetchSim(): Promise<SimulatorState> {
  const { data } = await api.GET("/api/sim")
  if (!data) {
    throw new Error("could not load the simulator")
  }
  return data
}

export function SimClock({
  initial,
  liveOnly = false,
}: {
  initial: SimulatorState | null
  liveOnly?: boolean
}) {
  const player = usePlayer()
  const fromRecording = useRecorded((prepared, cursor) =>
    simAt(prepared, cursor, simulatedAt(prepared.timeline, player.t))
  )
  const recorded = liveOnly
    ? { recording: false, data: undefined }
    : fromRecording
  const live = useQuery({
    queryKey: ["sim"],
    queryFn: fetchSim,
    initialData: initial ?? undefined,
    enabled: !recorded.recording,
    refetchInterval: (query) =>
      query.state.data?.run?.status === "running" ? CLOCK_MS : false,
  })
  const run = recorded.recording ? recorded.data : live.data?.run
  if (!run) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Simulated day</CardTitle>
          <CardDescription>
            {recorded.recording ? (
              "Waiting for the recorded day."
            ) : (
              <>
                No day has been played yet. Start one from the{" "}
                <Link
                  href="/admin/simulator"
                  className="underline underline-offset-4"
                >
                  simulator
                </Link>
                .
              </>
            )}
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }
  const total =
    new Date(run.ends_at).getTime() - new Date(run.started_at).getTime()
  const done =
    new Date(run.sim_now).getTime() - new Date(run.started_at).getTime()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span>Simulated day</span>
          <Badge variant={run.status === "running" ? "default" : "outline"}>
            {words(run.status)}
          </Badge>
        </CardTitle>
        <CardDescription>
          {run.scenario}, seed {run.seed}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <span className="text-2xl font-semibold tabular-nums">
          {moment(run.sim_now)}
        </span>
        <Progress value={Math.min(100, Math.round((done / total) * 100))} />
        <span className="text-xs text-muted-foreground">
          {run.agent_tickets} tickets to the agents
          {run.alerts_to_agents ? ", alerts to Ops" : ""}
        </span>
      </CardContent>
    </Card>
  )
}

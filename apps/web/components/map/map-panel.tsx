"use client"

import { PlayIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { useQuery } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useMemo } from "react"

import { useLive } from "@/components/live/live-provider"
import { CaptionLine } from "@/components/map/caption-line"
import { TeamMap } from "@/components/map/team-map"
import {
  usePlayer,
  useRecorded,
  useSource,
} from "@/components/recording/recording-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useLiveScene } from "@/hooks/use-live-scene"
import { api } from "@/lib/api/client"
import type { AgentSummary, Lineup, RecordingInfo } from "@/lib/api/types"
import { clock } from "@/lib/format"
import { agentsAt } from "@/lib/recording/derive"
import { realModels } from "@/lib/recording/load"
import { frameAt } from "@/lib/scene/frame"
import { buildTimeline } from "@/lib/scene/timeline"
import { cn } from "@/lib/utils"

async function fetchLineup(): Promise<Lineup> {
  const { data } = await api.GET("/api/lineup")
  if (!data) {
    throw new Error("could not load the lineup")
  }
  return data
}

async function fetchAgents(): Promise<AgentSummary[]> {
  const { data } = await api.GET("/api/agents")
  return data ?? []
}

function PlayCard({
  info,
  choices,
  onChoose,
  onPlay,
}: {
  info: RecordingInfo
  choices: RecordingInfo[]
  onChoose: (id: string) => void
  onPlay: () => void
}) {
  const summary = info.summary
  return (
    <div className="flex max-w-sm flex-col items-start gap-3 rounded-2xl border bg-card p-5 shadow-xl sm:p-6">
      <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
        Watch a day at the store
      </h2>
      <p className="text-sm text-muted-foreground">
        {realModels(info)
          ? `Recorded on real models, ${summary.profile} cost profile.`
          : "Recorded offline with rule-based agents."}
      </p>
      {choices.length > 1 ? (
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label="Recorded days"
        >
          {choices.map((choice) => (
            <Button
              key={choice.id}
              size="sm"
              variant={choice.id === info.id ? "default" : "outline"}
              onClick={() => onChoose(choice.id)}
            >
              {choice.title}
            </Button>
          ))}
        </div>
      ) : null}
      <Button size="lg" className="gap-2" onClick={onPlay}>
        <HugeiconsIcon icon={PlayIcon} className="size-4" />
        Play simulated day
      </Button>
    </div>
  )
}

export function MapPanel({ initialAgents }: { initialAgents: AgentSummary[] }) {
  const router = useRouter()
  const source = useSource()
  const player = usePlayer()
  const { status } = useLive()
  const recording = source.mode === "recording"
  const live =
    !recording &&
    Boolean(status && (status.simulating || status.active_work > 0))

  const lineup = useQuery({
    queryKey: ["lineup"],
    queryFn: fetchLineup,
    staleTime: 60_000,
    enabled: !recording,
  })
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents,
    initialData: initialAgents,
    enabled: !recording,
  })
  const recordedAgents = useRecorded(agentsAt)
  const idle = useMemo(() => buildTimeline([], lineup.data), [lineup.data])
  const scene = useLiveScene(lineup.data, live)

  const frame =
    recording && player.frame
      ? player.frame
      : live
        ? frameAt(scene.timeline, scene.t)
        : frameAt(idle, 0)
  const timeline = source.prepared?.timeline ?? null
  const inviting = recording && !player.playing && player.atEnd

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="relative bg-[var(--map-canvas)] px-3 pt-3 pb-2">
        <TeamMap
          frame={frame}
          agents={recording ? recordedAgents.data : agents.data}
          onPick={(workItemId) => router.push(`/runs/${workItemId}`)}
        />
        {inviting && source.selected ? (
          <div className="absolute inset-0 flex items-center justify-center bg-background/55 p-4 backdrop-blur-[2px]">
            <PlayCard
              info={source.selected}
              choices={source.recordings}
              onChoose={source.select}
              onPlay={player.start}
            />
          </div>
        ) : !recording && !live ? (
          <div className="absolute inset-0 flex items-center justify-center bg-background/55 p-4 backdrop-blur-[2px]">
            <div className="flex max-w-lg flex-col items-start gap-3 rounded-2xl border bg-card p-6 shadow-xl">
              <h2 className="text-xl font-semibold">Nothing running live</h2>
              <p className="text-sm text-muted-foreground">
                Start a day from the simulator to watch the team work, or watch
                the recorded day visitors see.
              </p>
              <Button
                className="gap-2"
                disabled={source.recordings.length === 0}
                onClick={() => source.setMode("recording")}
              >
                <HugeiconsIcon icon={PlayIcon} className="size-4" />
                Watch the recorded day
              </Button>
            </div>
          </div>
        ) : recording && !source.prepared ? (
          <div className="absolute inset-0 flex items-center justify-center bg-background/55 p-4">
            <p className="rounded-xl border bg-card px-5 py-4 text-sm text-muted-foreground">
              {source.loading
                ? "Loading the recorded day."
                : "No recorded day is published yet."}
            </p>
          </div>
        ) : null}
      </div>

      {recording && timeline && timeline.chapters.length > 0 ? (
        <div
          className="flex flex-wrap items-center gap-1.5 border-t px-4 py-3"
          role="group"
          aria-label="Chapters"
        >
          <span className="mr-1 text-xs text-muted-foreground">Jump to</span>
          {timeline.chapters.map((chapter) => {
            const reached = player.t >= chapter.at
            return (
              <button
                key={chapter.label}
                type="button"
                onClick={() => {
                  player.seek(chapter.at + 1)
                  player.play()
                }}
                className={cn(
                  "h-7 rounded-md border px-2 text-xs whitespace-nowrap",
                  reached
                    ? "border-[color-mix(in_oklch,var(--map-live)_45%,transparent)] bg-[color-mix(in_oklch,var(--map-live)_12%,transparent)] text-foreground"
                    : "text-muted-foreground hover:bg-muted"
                )}
              >
                {chapter.label}
                {player.day ? (
                  <span className="ml-1.5 font-mono text-[10px] text-muted-foreground">
                    {clock(
                      new Date(player.day.storeAt(chapter.at)).toISOString()
                    )}
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>
      ) : live ? (
        <div className="flex items-start gap-3 border-t px-4 py-3">
          <Badge className="mt-0.5 shrink-0 gap-1.5">
            <span className="size-1.5 animate-pulse rounded-full bg-current" />
            Live
          </Badge>
          <div className="min-w-0 flex-1">
            <CaptionLine
              frame={{
                ...frame,
                clock:
                  scene.clock === null
                    ? null
                    : clock(new Date(scene.clock).toISOString()),
              }}
            />
          </div>
        </div>
      ) : null}
    </Card>
  )
}

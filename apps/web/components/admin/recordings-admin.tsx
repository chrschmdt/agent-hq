"use client"

import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import { changeRecording, deleteRecording, recordDay } from "@/app/actions"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import type { RecordingInfo, SimRun } from "@/lib/api/types"
import { moment, usd, words } from "@/lib/format"

function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`
}

function useAction() {
  const router = useRouter()
  const [pending, startTransition] = useTransition()
  const run = (
    action: () => Promise<{ ok: true } | { ok: false; error: string }>,
    done: string
  ) =>
    startTransition(async () => {
      const result = await action()
      if (!result.ok) {
        toast.error(result.error)
        return
      }
      toast.success(done)
      router.refresh()
    })
  return { pending, run }
}

function DayRow({ day, recorded }: { day: SimRun; recorded: number }) {
  const [title, setTitle] = useState("")
  const { pending, run } = useAction()
  const finished = day.status === "finished" || day.status === "stopped"
  return (
    <div className="flex flex-col gap-3 border-t py-4 first:border-t-0 first:pt-0 md:flex-row md:items-center md:justify-between">
      <div className="flex flex-col gap-1">
        <span className="font-medium">
          {words(day.scenario)}, seed {day.seed}
        </span>
        <span className="text-xs text-muted-foreground">
          Played {moment(day.created_at)}; {day.agent_tickets} tickets to the
          agents{day.alerts_to_agents ? ", alerts to Ops" : ""}.{" "}
          {recorded > 0
            ? `Recorded ${recorded === 1 ? "once" : `${recorded} times`}.`
            : ""}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={finished ? "outline" : "default"}>
          {words(day.status)}
        </Badge>
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Title (optional)"
          aria-label="Title for the recording"
          className="w-48"
          disabled={!finished}
        />
        <Button
          disabled={!finished || pending}
          onClick={() =>
            run(
              () => recordDay(day.run_id, title.trim() || null),
              "Recorded and published. Visitors see it now."
            )
          }
        >
          {pending ? "Recording..." : "Record and publish"}
        </Button>
      </div>
    </div>
  )
}

function RecordingRow({ info }: { info: RecordingInfo }) {
  const [title, setTitle] = useState(info.title)
  const [confirming, setConfirming] = useState(false)
  const { pending, run } = useAction()
  const summary = info.summary
  return (
    <div className="flex flex-col gap-3 border-t py-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            aria-label="Recording title"
            className="max-w-md"
          />
          {title.trim() && title.trim() !== info.title ? (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() =>
                run(
                  () => changeRecording(info.id, { title: title.trim() }),
                  "Renamed."
                )
              }
            >
              Save
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={info.published}
              disabled={pending}
              onCheckedChange={(published) =>
                run(
                  () => changeRecording(info.id, { published }),
                  published
                    ? "Published. Visitors see it now."
                    : "Withdrawn. Visitors no longer see it."
                )
              }
            />
            Published
          </label>
          {confirming ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={pending}
                onClick={() => run(() => deleteRecording(info.id), "Deleted.")}
              >
                Delete for good
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirming(false)}
              >
                Keep
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConfirming(true)}
            >
              Delete
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {words(summary.scenario)}, seed {summary.seed}, on the {summary.profile}{" "}
        profile: {count(summary.tickets, "ticket")}, {summary.agent_tickets} to
        the agents, {count(summary.model_calls, "model call")},{" "}
        {count(summary.tool_calls, "tool call")},{" "}
        {count(summary.approvals, "approval")},{" "}
        {count(summary.incidents, "incident")}, {usd(summary.cost_usd)}.
        Recorded {moment(info.created_at)} by {info.created_by};{" "}
        {(info.size_bytes / 1e6).toFixed(2)} MB compressed.
      </p>
    </div>
  )
}

export function RecordingsAdmin({
  days,
  recordings,
}: {
  days: SimRun[]
  recordings: RecordingInfo[]
}) {
  const recordedTimes = (runId: string) =>
    recordings.filter((info) => info.sim_run_id === runId).length
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Recorded days</CardTitle>
          <CardDescription>
            Visitors only ever see published recordings: every page of the
            control room replays the newest by default, and they can choose
            another. Live days are yours alone. A recording keeps everything it
            shows, so clearing the activity leaves it intact.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {recordings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              None yet. Record a finished day below.
            </p>
          ) : (
            recordings.map((info) => <RecordingRow key={info.id} info={info} />)
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Simulated days</CardTitle>
          <CardDescription>
            Days played on this deployment, newest first. Record one once it has
            finished; recording it again makes a new recording.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {days.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No day has been played yet. Start one from the simulator.
            </p>
          ) : (
            days.map((day) => (
              <DayRow
                key={day.run_id}
                day={day}
                recorded={recordedTimes(day.run_id)}
              />
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}

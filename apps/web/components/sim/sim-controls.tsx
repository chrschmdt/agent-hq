"use client"

import {
  PauseIcon,
  PlayIcon,
  RefreshIcon,
  StopIcon,
} from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import {
  type ActionResult,
  controlSimulation,
  resetSimulation,
  startSimulation,
} from "@/app/actions"
import { SimClock, fetchSim } from "@/components/overview/sim-clock"
import { useAdmin } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import type { SimulatorState } from "@/lib/api/types"
import { MAX_AGENT_TICKETS, agentTicketsError } from "@/lib/sim"

const SPEEDS = [
  { value: "6.25", label: "a day in about 30 minutes" },
  { value: "2", label: "a day in about 10 minutes" },
  { value: "1", label: "a day in about 5 minutes" },
  { value: "0.5", label: "a day in under 3 minutes" },
]

export function SimControls({ initial }: { initial: SimulatorState }) {
  const admin = useAdmin()
  const client = useQueryClient()
  const { data } = useQuery({
    queryKey: ["sim"],
    queryFn: fetchSim,
    initialData: initial,
    refetchInterval: (query) =>
      query.state.data?.run?.status === "running" ? 2000 : false,
  })
  const [scenario, setScenario] = useState(
    initial.scenarios[0]?.name ?? "normal-day"
  )
  const [seed, setSeed] = useState("7")
  const [tickets, setTickets] = useState("3")
  const [alerts, setAlerts] = useState(true)
  const [speed, setSpeed] = useState("1")
  const [pending, startTransition] = useTransition()
  const run = data.run
  const active = run?.status === "running" || run?.status === "paused"
  const chosen = data.scenarios.find((option) => option.name === scenario)
  const ticketsError = agentTicketsError(tickets)

  const act = (label: string, action: () => Promise<ActionResult<unknown>>) =>
    startTransition(async () => {
      const result = await action()
      if (result.ok) {
        toast.success(label)
        await client.invalidateQueries({ queryKey: ["sim"] })
      } else {
        toast.error(result.error)
      }
    })

  const start = () =>
    act("The day has started.", () =>
      startSimulation({
        scenario,
        seed: Number(seed) || 7,
        agent_tickets: Number(tickets),
        alerts_to_agents: alerts,
        tick_seconds: Number(speed),
      })
    )

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <Card>
        <CardHeader>
          <CardTitle>Play a day</CardTitle>
          <CardDescription>
            {admin
              ? "Starting a day resets the store to its baseline first."
              : "Sign in as the admin to play a day; agents answering tickets cost model calls."}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label>Scenario</Label>
            <Select
              value={scenario}
              onValueChange={(value) => {
                const next = data.scenarios.find(
                  (option) => option.name === value
                )
                setScenario(String(value))
                if (next) {
                  setTickets(
                    String(
                      next.wave_tickets > 0
                        ? next.agent_tickets
                        : Math.max(3, next.agent_tickets)
                    )
                  )
                  setAlerts(next.alerts_to_agents || next.agent_tickets === 0)
                }
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {data.scenarios.map((option) => (
                  <SelectItem key={option.name} value={option.name}>
                    {option.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {chosen?.description}
              {chosen && chosen.wave_tickets > 0
                ? ` Its ${chosen.wave_tickets} extra customers go to the agents in any case.`
                : null}
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="seed">Seed</Label>
            <Input
              id="seed"
              value={seed}
              onChange={(event) => setSeed(event.target.value)}
              inputMode="numeric"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tickets">
              Tickets for the agents (0 to {MAX_AGENT_TICKETS})
            </Label>
            <Input
              id="tickets"
              value={tickets}
              onChange={(event) => setTickets(event.target.value)}
              inputMode="numeric"
              aria-invalid={ticketsError ? true : undefined}
              aria-describedby={ticketsError ? "tickets-error" : undefined}
            />
            {ticketsError ? (
              <p id="tickets-error" className="text-xs text-destructive">
                {ticketsError}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Speed</Label>
            <Select
              value={speed}
              onValueChange={(value) => setSpeed(String(value))}
              items={SPEEDS}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SPEEDS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2 self-end pb-2">
            <Switch id="alerts" checked={alerts} onCheckedChange={setAlerts} />
            <Label htmlFor="alerts">Alerts go to the Ops analyst</Label>
          </div>
        </CardContent>
        <CardFooter className="flex flex-wrap justify-end gap-2">
          <Button
            variant="outline"
            onClick={() =>
              act("The store is back at its baseline.", resetSimulation)
            }
            disabled={!admin || pending}
          >
            <HugeiconsIcon icon={RefreshIcon} />
            Reset
          </Button>
          <Button
            onClick={start}
            disabled={!admin || pending || ticketsError !== null}
          >
            <HugeiconsIcon icon={PlayIcon} />
            {active ? "Start over" : "Start"}
          </Button>
        </CardFooter>
      </Card>
      <div className="flex flex-col gap-4">
        <SimClock initial={data} liveOnly />
        {run && active ? (
          <div className="flex gap-2">
            {run.status === "running" ? (
              <Button
                variant="outline"
                className="flex-1"
                onClick={() =>
                  act("Paused.", () => controlSimulation(run.run_id, "pause"))
                }
                disabled={!admin || pending}
              >
                <HugeiconsIcon icon={PauseIcon} />
                Pause
              </Button>
            ) : (
              <Button
                variant="outline"
                className="flex-1"
                onClick={() =>
                  act("Resumed.", () => controlSimulation(run.run_id, "resume"))
                }
                disabled={!admin || pending}
              >
                <HugeiconsIcon icon={PlayIcon} />
                Resume
              </Button>
            )}
            <Button
              variant="destructive"
              className="flex-1"
              onClick={() =>
                act("Stopped.", () => controlSimulation(run.run_id, "stop"))
              }
              disabled={!admin || pending}
            >
              <HugeiconsIcon icon={StopIcon} />
              Stop
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}

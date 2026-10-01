"use client"

import { PauseIcon, PlayIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useTransition } from "react"
import { toast } from "sonner"

import { controlSimulation } from "@/app/actions"
import { fetchSim } from "@/components/overview/sim-clock"
import { pendingProposals } from "@/components/overview/status-bar"
import { useCanAct } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { useStatus } from "@/hooks/use-status"
import { clock } from "@/lib/format"
import { cn } from "@/lib/utils"

const CLOCK_MS = 2000

function Waiting({
  href,
  count,
  noun,
}: {
  href: string
  count: number
  noun: string
}) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-full px-3 py-1 text-xs whitespace-nowrap tabular-nums transition-colors hover:bg-muted",
        count > 0
          ? "bg-[var(--map-amber)]/15 font-medium text-[var(--map-amber)]"
          : "text-muted-foreground"
      )}
    >
      {count} {noun}
      {count === 1 ? "" : "s"}
      <span className="hidden sm:inline"> waiting</span>
    </Link>
  )
}

export function SimDock() {
  const canAct = useCanAct()
  const client = useQueryClient()
  const status = useStatus()
  const [pending, startTransition] = useTransition()
  const sim = useQuery({
    queryKey: ["sim"],
    queryFn: fetchSim,
    enabled: canAct,
    refetchInterval: (query) =>
      query.state.data?.run?.status === "running" ? CLOCK_MS : false,
  })
  const run = sim.data?.run
  const active = run?.status === "running" || run?.status === "paused"
  const proposals = useQuery({
    queryKey: ["proposals", "pending"],
    queryFn: pendingProposals,
    enabled: canAct && active,
  })
  if (!canAct || !run || !active) {
    return null
  }
  const running = run.status === "running"
  const total =
    new Date(run.ends_at).getTime() - new Date(run.started_at).getTime()
  const done =
    new Date(run.sim_now).getTime() - new Date(run.started_at).getTime()
  const toggle = () =>
    startTransition(async () => {
      const result = await controlSimulation(
        run.run_id,
        running ? "pause" : "resume"
      )
      if (result.ok) {
        await client.invalidateQueries({ queryKey: ["sim"] })
      } else {
        toast.error(result.error)
      }
    })
  return (
    <div className="sticky bottom-0 z-20 border-t bg-background/92 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-2.5 md:px-8">
        <Button
          size="icon"
          className="size-10 shrink-0 rounded-full"
          onClick={toggle}
          disabled={pending}
          aria-label={running ? "Pause the day" : "Resume the day"}
        >
          <HugeiconsIcon
            icon={running ? PauseIcon : PlayIcon}
            className="size-5"
          />
        </Button>
        <span
          className="shrink-0 font-mono text-sm tabular-nums"
          title="The store's time"
        >
          {clock(run.sim_now)}
        </span>
        <div className="hidden min-w-0 flex-1 flex-col gap-1 sm:flex">
          <span className="truncate text-xs text-muted-foreground">
            {run.scenario}, seed {run.seed}, {running ? "running" : "paused"}
          </span>
          <Progress value={Math.min(100, Math.round((done / total) * 100))} />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <Waiting
            href="/approvals"
            count={status?.pending_approvals ?? 0}
            noun="approval"
          />
          <Waiting
            href="/proposals"
            count={proposals.data ?? 0}
            noun="proposal"
          />
        </div>
        <Link
          href="/admin/simulator"
          className="hidden shrink-0 text-xs text-muted-foreground underline-offset-4 hover:underline md:inline"
        >
          Simulator
        </Link>
      </div>
    </div>
  )
}

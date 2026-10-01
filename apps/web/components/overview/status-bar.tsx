"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { useRecorded } from "@/components/recording/recording-provider"
import { useStatus } from "@/hooks/use-status"
import { api } from "@/lib/api/client"
import type { Status } from "@/lib/api/types"
import { incidentsAt, proposalsAt } from "@/lib/recording/derive"
import { cn } from "@/lib/utils"

async function openIncidents(): Promise<number> {
  const { data } = await api.GET("/api/incidents")
  return (data ?? []).filter((incident) => incident.status === "open").length
}

export async function pendingProposals(): Promise<number> {
  const { data } = await api.GET("/api/proposals", {
    params: { query: { status: "pending" } },
  })
  return (data ?? []).length
}

type Counter = {
  href: string
  label: string
  value: number | undefined
  hint: string
  alert: boolean
}

export function StatusBar({ initial }: { initial: Status | null }) {
  const status = useStatus() ?? initial ?? undefined
  const recorded = useRecorded((prepared, cursor) => ({
    incidents: incidentsAt(prepared, cursor).filter(
      (incident) => incident.status === "open"
    ).length,
    proposals: proposalsAt(prepared, cursor).filter(
      (proposal) => proposal.status === "pending"
    ).length,
  }))
  const incidents = useQuery({
    queryKey: ["incidents", "open"],
    queryFn: openIncidents,
    enabled: !recorded.recording,
  })
  const proposals = useQuery({
    queryKey: ["proposals", "pending"],
    queryFn: pendingProposals,
    enabled: !recorded.recording,
  })
  const counters: Counter[] = [
    {
      href: "/work",
      label: "Active work",
      value: status?.active_work,
      hint: "Work items new or running",
      alert: false,
    },
    {
      href: "/approvals",
      label: "Approvals waiting",
      value: status?.pending_approvals,
      hint: "Actions that wait for a person",
      alert: (status?.pending_approvals ?? 0) > 0,
    },
    {
      href: "/incidents",
      label: "Open incidents",
      value: recorded.recording ? recorded.data?.incidents : incidents.data,
      hint: "Filed by the Ops analyst",
      alert: false,
    },
    {
      href: "/proposals",
      label: "Proposals to review",
      value: recorded.recording ? recorded.data?.proposals : proposals.data,
      hint: "Drafted by Insights",
      alert: false,
    },
  ]
  return (
    <section
      aria-label="What needs attention"
      className="grid grid-cols-2 overflow-hidden rounded-xl border bg-card md:grid-cols-4"
    >
      {counters.map((counter, index) => (
        <Link
          key={counter.href}
          href={counter.href}
          className={cn(
            "flex flex-col gap-0.5 px-4 py-3 transition-colors hover:bg-muted/60 sm:px-5 sm:py-4",
            index % 2 === 1 && "border-l",
            index >= 2 && "border-t md:border-t-0",
            index === 2 && "md:border-l"
          )}
        >
          <span className="text-xs text-muted-foreground">{counter.label}</span>
          <span
            className={cn(
              "text-2xl font-semibold tabular-nums sm:text-3xl",
              counter.alert && "text-[var(--map-amber)]"
            )}
          >
            {counter.value ?? "..."}
          </span>
          <span className="hidden text-xs text-muted-foreground sm:block">
            {counter.hint}
          </span>
        </Link>
      ))}
    </section>
  )
}

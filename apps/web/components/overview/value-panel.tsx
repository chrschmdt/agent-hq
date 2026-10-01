"use client"

import { useQuery } from "@tanstack/react-query"

import { useRecorded } from "@/components/recording/recording-provider"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { api } from "@/lib/api/client"
import type { TeamValue } from "@/lib/api/types"
import { percent, usd } from "@/lib/format"
import { valueAt } from "@/lib/recording/derive"

function Figure({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xl font-semibold tabular-nums">{value}</span>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </div>
  )
}

export function ValuePanel({ initial }: { initial: TeamValue | null }) {
  const recorded = useRecorded(valueAt)
  const live = useQuery({
    queryKey: ["value"],
    queryFn: async () => (await api.GET("/api/value")).data ?? null,
    initialData: initial,
    enabled: !recorded.recording,
  })
  const value = recorded.recording ? recorded.data : live.data
  if (!value) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Value</CardTitle>
          <CardDescription>
            What the ticket work cost, against a person doing it, once the first
            ticket is in.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }
  const person = usd(value.human_cost_per_ticket_usd)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Value</CardTitle>
        <CardDescription>
          Ticket work so far, against a person at {person} a ticket, an
          assumption set in the config.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-5 md:grid-cols-3 xl:grid-cols-6">
        <Figure
          label="Net savings"
          value={usd(value.net_savings_usd)}
          hint={`people would cost ${usd(value.human_cost_usd)} for ${value.resolved} resolved`}
        />
        <Figure
          label="Cost per resolved ticket"
          value={
            value.cost_per_resolved_usd === null
              ? "n/a"
              : usd(value.cost_per_resolved_usd)
          }
          hint={`against ${person} for a person`}
        />
        <Figure
          label="Resolved without a person"
          value={
            value.deflection_rate === null
              ? "n/a"
              : percent(value.deflection_rate)
          }
          hint={`${value.resolved} resolved, ${value.with_people} with people`}
        />
        <Figure
          label="Time to resolve"
          value={
            value.median_minutes_to_resolve === null
              ? "n/a"
              : `${value.median_minutes_to_resolve} min`
          }
          hint="median, from taking a ticket to resolving it"
        />
        <Figure
          label="Approvals per 100 tickets"
          value={
            value.approvals_per_100 === null
              ? "n/a"
              : String(value.approvals_per_100)
          }
          hint={`${value.tickets} tickets taken`}
        />
        <Figure
          label="Reached before writing in"
          value={
            value.delayed_customers
              ? `${value.reached_first} of ${value.delayed_customers}`
              : "n/a"
          }
          hint={`delayed customers, over ${value.incidents} incidents`}
        />
      </CardContent>
    </Card>
  )
}

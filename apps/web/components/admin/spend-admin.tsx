"use client"

import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import { pauseAgent, resumeAgent } from "@/app/actions"
import { Ago } from "@/components/ago"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import type { AgentLimits, LimitsView } from "@/lib/api/types"
import { sentence, usd } from "@/lib/format"

const NAMES: Record<string, string> = { qa: "QA reviewer" }

function Spend({ spent, budget }: { spent: number; budget: number | null }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-sm">
        <span className="text-muted-foreground">Spent today</span>
        <span className="tabular-nums">
          {usd(spent)}
          {budget ? ` of ${usd(budget)}` : ""}
        </span>
      </div>
      {budget ? (
        <Progress value={Math.min(100, (spent / budget) * 100)} />
      ) : null}
    </div>
  )
}

function AgentRow({ row }: { row: AgentLimits }) {
  const router = useRouter()
  const [reason, setReason] = useState("")
  const [pending, startTransition] = useTransition()
  const toggle = () =>
    startTransition(async () => {
      const result = row.paused
        ? await resumeAgent(row.agent)
        : await pauseAgent(row.agent, reason.trim())
      if (!result.ok) {
        toast.error(result.error)
        return
      }
      toast.success(
        row.paused ? `${row.agent} is back at work.` : `${row.agent} is paused.`
      )
      setReason("")
      router.refresh()
    })
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{NAMES[row.agent] ?? sentence(row.agent)}</CardTitle>
        <CardDescription>
          {row.calls_today} model calls today, {row.errors_today} failed.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <Spend spent={row.spent_today_usd} budget={row.budget_usd} />
        <p>
          {row.paused ? (
            <>
              <span className="font-medium text-[var(--map-amber)]">
                Paused
              </span>{" "}
              by {row.changed_by}
              {row.changed_at ? (
                <>
                  {" "}
                  <Ago iso={row.changed_at} />
                </>
              ) : null}
              : {row.reason}
            </>
          ) : (
            <span className="text-muted-foreground">Taking work.</span>
          )}
        </p>
        {row.paused ? (
          <Button variant="outline" onClick={toggle} disabled={pending}>
            Resume
          </Button>
        ) : (
          <div className="flex gap-2">
            <Input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why pause it?"
              aria-label={`Why pause ${row.agent}`}
            />
            <Button
              variant="destructive"
              onClick={toggle}
              disabled={pending || reason.trim().length < 3}
            >
              Pause
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function SpendAdmin({ limits }: { limits: LimitsView }) {
  const open = (limits.models ?? []).filter(
    (health) => health.open_until && new Date(health.open_until) > new Date()
  )
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>All agents, {limits.day}</CardTitle>
          <CardDescription>
            Budgets reset at midnight UTC. An agent over its budget, or paused,
            hands its work to a person.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Spend
            spent={limits.total_spent_usd}
            budget={limits.total_budget_usd}
          />
        </CardContent>
      </Card>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {limits.agents.map((row) => (
          <AgentRow key={row.agent} row={row} />
        ))}
      </section>
      <Card>
        <CardHeader>
          <CardTitle>Breakers</CardTitle>
          <CardDescription>
            A model whose calls fail several times in a row hands its calls to
            its fallback until the cooldown ends.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-1 text-sm">
          {open.length === 0 ? (
            <p className="text-muted-foreground">Every breaker is closed.</p>
          ) : (
            open.map((health) => (
              <p key={health.model}>
                <span className="font-mono text-xs">{health.model}</span>:{" "}
                {health.consecutive_errors} errors in a row
                {health.last_error ? `, last: ${health.last_error}` : ""}
              </p>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}

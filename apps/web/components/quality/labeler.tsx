"use client"

import { useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useCallback, useEffect, useMemo, useState, useTransition } from "react"
import { toast } from "sonner"

import { labelRun } from "@/app/actions"
import { Ago } from "@/components/ago"
import { RunMaterial } from "@/components/quality/run-material"
import { VerdictBadge } from "@/components/quality/verdict-badge"
import { useAdmin } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { api } from "@/lib/api/client"
import type { LabelOutcome, LabelTask } from "@/lib/api/types"
import { agreement } from "@/lib/management"
import { cn } from "@/lib/utils"
import { version } from "@/lib/format"

type Choice = "pass" | "fail" | "skip"

async function fetchTask(): Promise<LabelTask | null> {
  const { data } = await api.GET("/api/qa/queue", {
    params: { query: { limit: 1 } },
  })
  return data?.[0] ?? null
}

export function Labeler({ initial }: { initial: LabelTask | null }) {
  const admin = useAdmin()
  const client = useQueryClient()
  const { data: task } = useQuery({
    queryKey: ["qa", "queue"],
    queryFn: fetchTask,
    initialData: initial,
  })
  const [choices, setChoices] = useState<Record<string, Choice>>({})
  const [current, setCurrent] = useState(0)
  const [outcome, setOutcome] = useState<LabelOutcome | null>(null)
  const [pending, startTransition] = useTransition()
  const criteria = useMemo(() => task?.criteria ?? [], [task])
  const labels = Object.fromEntries(
    Object.entries(choices).filter(([, choice]) => choice !== "skip")
  ) as Record<string, "pass" | "fail">

  const choose = useCallback(
    (index: number, choice: Choice) => {
      const criterion = criteria[index]
      if (!criterion) {
        return
      }
      setChoices((all) => ({ ...all, [criterion.id]: choice }))
      setCurrent(Math.min(index + 1, criteria.length - 1))
    },
    [criteria]
  )

  const save = useCallback(() => {
    if (!task || Object.keys(labels).length === 0) {
      return
    }
    startTransition(async () => {
      const result = await labelRun(task.work_item_id, task.agent, labels)
      if (result.ok) {
        setOutcome(result.data)
      } else {
        toast.error(result.error)
      }
    })
  }, [task, labels])

  const next = async () => {
    setChoices({})
    setCurrent(0)
    setOutcome(null)
    await client.invalidateQueries({ queryKey: ["qa"] })
  }

  useEffect(() => {
    if (!admin || outcome) {
      return
    }
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (target.closest("input, textarea")) {
        return
      }
      const keys: Record<string, Choice> = { p: "pass", f: "fail", s: "skip" }
      if (keys[event.key]) {
        choose(current, keys[event.key])
      } else if (event.key === "Enter") {
        save()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [admin, outcome, current, choose, save])

  if (!task) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Nothing to label</CardTitle>
          <CardDescription>
            Every reviewed run has labels. Reviews arrive as runs finish: a
            sample of them, every escalation, every rejected action and every
            canary run.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }
  const agrees = outcome ? agreement(labels, outcome.review) : {}
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_26rem]">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span className="capitalize">{task.agent}</span>
            <span className="font-mono text-sm text-muted-foreground">
              {version(task.version_id)}
            </span>
          </CardTitle>
          <CardDescription>
            Reviewed <Ago iso={task.reviewed_at} />.{" "}
            <Link
              href={`/runs/${task.work_item_id}`}
              className="underline underline-offset-4"
            >
              The whole run
            </Link>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RunMaterial material={task.material} />
        </CardContent>
      </Card>
      <Card className="self-start">
        <CardHeader>
          <CardTitle>
            {outcome ? "You and the reviewer" : "Your labels"}
          </CardTitle>
          <CardDescription>
            {admin
              ? outcome
                ? "Agreement on labeled runs is what calibrates the reviewer."
                : "Judge each criterion from the run alone. Skip what you cannot tell."
              : "Sign in as the admin to label runs."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {criteria.map((criterion, index) => {
            const mine = choices[criterion.id]
            const review = outcome?.review.criteria.find(
              (verdict) => verdict.criterion_id === criterion.id
            )
            return (
              <div
                key={criterion.id}
                className={cn(
                  "flex flex-col gap-2 rounded-lg border p-3",
                  !outcome && index === current && admin && "border-primary"
                )}
              >
                <p className="text-sm font-medium">{criterion.title}</p>
                <p className="text-xs text-muted-foreground">
                  {criterion.question}
                </p>
                {outcome ? (
                  <div className="flex flex-col gap-1 text-xs">
                    <p className="flex items-center gap-2">
                      You:{" "}
                      {mine && mine !== "skip" ? (
                        <VerdictBadge verdict={mine} />
                      ) : (
                        "skipped"
                      )}
                      Reviewer:{" "}
                      {review ? (
                        <VerdictBadge verdict={review.verdict} />
                      ) : (
                        "none"
                      )}
                      {criterion.id in agrees ? (
                        <span
                          className={
                            agrees[criterion.id]
                              ? "text-emerald-700 dark:text-emerald-300"
                              : "text-amber-700 dark:text-amber-300"
                          }
                        >
                          {agrees[criterion.id] ? "agree" : "differ"}
                        </span>
                      ) : null}
                    </p>
                    {review ? (
                      <p className="text-muted-foreground">{review.critique}</p>
                    ) : null}
                  </div>
                ) : admin ? (
                  <div className="flex gap-1.5">
                    {(["pass", "fail", "skip"] as const).map((choice) => (
                      <Button
                        key={choice}
                        size="sm"
                        variant={mine === choice ? "default" : "outline"}
                        onClick={() => choose(index, choice)}
                      >
                        {choice}
                      </Button>
                    ))}
                  </div>
                ) : null}
              </div>
            )
          })}
          {admin ? (
            outcome ? (
              <Button onClick={next}>Next run</Button>
            ) : (
              <Button
                onClick={save}
                disabled={pending || Object.keys(labels).length === 0}
              >
                Save labels
              </Button>
            )
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

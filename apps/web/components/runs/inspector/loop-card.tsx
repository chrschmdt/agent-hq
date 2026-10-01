"use client"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { name, type Pass } from "@/lib/inspector/passes"

type Step = "model" | "check" | "wait" | "tools" | "answer"

const BOXES: Record<Step, { x: number; y: number; w: number; label: string }> =
  {
    model: { x: 128, y: 10, w: 160, label: "Call the model" },
    check: { x: 262, y: 112, w: 150, label: "Check permissions" },
    wait: { x: 250, y: 228, w: 150, label: "Wait for you" },
    tools: { x: 42, y: 228, w: 150, label: "Run tools" },
    answer: { x: 4, y: 112, w: 130, label: "Answer" },
  }
const HEIGHT = 50

const ARROWS: { d: string; head: string; steps: [Step, Step] }[] = [
  {
    d: "M288 36 Q337 50 337 112",
    head: "M332 104 L337 112 L342 104 Z",
    steps: ["model", "check"],
  },
  {
    d: "M331 162 L326 228",
    head: "M321 220 L326 228 L331 220 Z",
    steps: ["check", "wait"],
  },
  {
    d: "M262 150 Q205 190 172 228",
    head: "M167 219 L172 228 L179 221 Z",
    steps: ["check", "tools"],
  },
  {
    d: "M250 253 L192 253",
    head: "M200 248 L192 253 L200 258 Z",
    steps: ["wait", "tools"],
  },
  {
    d: "M96 228 Q104 110 150 60",
    head: "M141 63 L150 60 L148 69 Z",
    steps: ["tools", "model"],
  },
  {
    d: "M128 36 Q68 48 69 112",
    head: "M64 104 L69 112 L74 104 Z",
    steps: ["model", "answer"],
  },
]

function stepsOf(pass: Pass | undefined): Set<Step> {
  if (!pass) {
    return new Set()
  }
  const steps = new Set<Step>(["model"])
  if (pass.calls.length > 0) {
    steps.add("check")
    if (
      pass.calls.some(
        (call) => call.verdict !== "refused" && call.verdict !== "pending"
      )
    ) {
      steps.add("tools")
    }
    if (pass.calls.some((call) => call.approval !== null)) {
      steps.add("wait")
    }
  } else {
    steps.add("answer")
  }
  return steps
}

export function LoopCard({
  passes,
  agents,
  agent,
  selected,
  onAgent,
}: {
  passes: Pass[]
  agents: string[]
  agent: string
  selected: Pass | undefined
  onAgent: (agent: string) => void
}) {
  const mine = passes.filter((pass) => pass.agent === agent && !pass.repair)
  const counts: Record<Step, number> = {
    model: mine.length,
    check: mine.filter((p) => p.calls.length > 0).length,
    wait: mine.reduce(
      (sum, p) => sum + p.calls.filter((c) => c.approval !== null).length,
      0
    ),
    tools: mine.reduce(
      (sum, p) =>
        sum +
        p.calls.filter(
          (c) => c.verdict !== "refused" && c.verdict !== "pending"
        ).length,
      0
    ),
    answer: mine.filter((p) => p.answer !== null).length,
  }
  const hot = stepsOf(selected?.agent === agent ? selected : undefined)
  const detail: Record<Step, string> = {
    model: `${counts.model} time${counts.model === 1 ? "" : "s"}`,
    check: `${counts.check} time${counts.check === 1 ? "" : "s"}`,
    wait: counts.wait
      ? `${counts.wait} approval${counts.wait === 1 ? "" : "s"}`
      : "not needed",
    tools: `${counts.tools} call${counts.tools === 1 ? "" : "s"}`,
    answer:
      agent === "support"
        ? `${counts.answer} repl${counts.answer === 1 ? "y" : "ies"}, checked`
        : `${counts.answer} typed`,
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>The agent loop</CardTitle>
        <CardDescription>
          {selected
            ? `${name(selected.agent)}, pass ${selected.n}, lit.`
            : "Pick a pass to follow it."}{" "}
          Side effects happen only in Run tools, after any wait.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {agents.length > 1 ? (
          <div className="flex gap-1" role="group" aria-label="Agent">
            {agents.map((option) => (
              <Button
                key={option}
                size="sm"
                variant={option === agent ? "default" : "outline"}
                onClick={() => onAgent(option)}
              >
                {name(option)}
              </Button>
            ))}
          </div>
        ) : null}
        <svg
          viewBox="0 0 416 284"
          className="w-full max-w-[26rem] self-center"
          role="img"
          aria-label={`${name(agent)}'s loop`}
        >
          {ARROWS.map((arrow) => {
            const lit = hot.has(arrow.steps[0]) && hot.has(arrow.steps[1])
            const color = lit ? "var(--map-live)" : "var(--map-line)"
            return (
              <g key={arrow.d}>
                <path
                  d={arrow.d}
                  fill="none"
                  stroke={color}
                  strokeOpacity={lit ? 1 : 0.4}
                  strokeWidth={lit ? 2.2 : 1.5}
                />
                <path d={arrow.head} fill={color} fillOpacity={lit ? 1 : 0.5} />
              </g>
            )
          })}
          {(Object.keys(BOXES) as Step[]).map((step) => {
            const box = BOXES[step]
            const lit = hot.has(step)
            const tone =
              step === "wait" ? "var(--map-amber)" : "var(--map-live)"
            return (
              <g key={step}>
                <rect
                  x={box.x}
                  y={box.y}
                  width={box.w}
                  height={HEIGHT}
                  rx={10}
                  fill={
                    lit
                      ? `color-mix(in oklch, ${tone} 14%, var(--card))`
                      : "var(--card)"
                  }
                  stroke={lit ? tone : "var(--border)"}
                  strokeWidth={lit ? 1.5 : 1}
                />
                <text
                  x={box.x + box.w / 2}
                  y={box.y + 21}
                  textAnchor="middle"
                  className="fill-foreground text-[13px] font-semibold"
                >
                  {box.label}
                </text>
                <text
                  x={box.x + box.w / 2}
                  y={box.y + 38}
                  textAnchor="middle"
                  className="fill-muted-foreground font-mono text-[11px]"
                >
                  {detail[step]}
                </text>
              </g>
            )
          })}
        </svg>
      </CardContent>
    </Card>
  )
}

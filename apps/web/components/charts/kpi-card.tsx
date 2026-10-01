"use client"

import { Area, AreaChart, XAxis } from "recharts"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import type { KpiPoint } from "@/lib/api/types"
import { percent } from "@/lib/format"

export type KpiUnit = "count" | "rate" | "score"

function show(value: number, unit: KpiUnit): string {
  if (unit === "rate") {
    return percent(value)
  }
  return unit === "score" ? value.toFixed(2) : Math.round(value).toString()
}

const CONFIG = {
  value: { label: "Value", color: "var(--primary)" },
} satisfies ChartConfig

export function KpiCard({
  label,
  unit,
  points,
  higherIsBetter = true,
}: {
  label: string
  unit: KpiUnit
  points: KpiPoint[]
  higherIsBetter?: boolean
}) {
  const latest = points.at(-1)
  const previous = points.at(-2)
  const change = latest && previous ? latest.value - previous.value : 0
  const good = change === 0 || change > 0 === higherIsBetter
  const data = points.map((point) => ({ day: point.day, value: point.value }))
  return (
    <Card className="gap-2">
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold tabular-nums">
            {latest ? show(latest.value, unit) : "none"}
          </span>
          {latest && previous ? (
            <span
              className={
                good
                  ? "text-xs text-emerald-600 dark:text-emerald-400"
                  : "text-xs text-amber-600 dark:text-amber-400"
              }
            >
              {change >= 0 ? "+" : ""}
              {show(change, unit)} on the day before
            </span>
          ) : null}
        </div>
        <ChartContainer config={CONFIG} className="aspect-auto h-14 w-full">
          <AreaChart
            data={data}
            margin={{ left: 0, right: 0, top: 2, bottom: 0 }}
          >
            <XAxis dataKey="day" hide />
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  hideIndicator
                  formatter={(value) => show(Number(value), unit)}
                />
              }
            />
            <Area
              dataKey="value"
              type="monotone"
              stroke="var(--color-value)"
              fill="var(--color-value)"
              fillOpacity={0.12}
              strokeWidth={1.5}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

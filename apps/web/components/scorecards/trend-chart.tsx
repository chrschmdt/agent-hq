"use client"

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts"

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import type { MetricDef, VersionCard } from "@/lib/api/types"
import { metricText } from "@/lib/management"
import { version } from "@/lib/format"

const COLORS = [
  "var(--primary)",
  "oklch(0.72 0.15 65)",
  "var(--chart-2)",
  "var(--chart-4)",
]

export function TrendChart({
  def,
  cards,
}: {
  def: MetricDef
  cards: VersionCard[]
}) {
  const series = cards
    .filter((card) => card.trend.length > 0)
    .map((card, index) => ({ key: `v${index}`, card }))
  const rows = new Map<number, Record<string, number>>()
  for (const { key, card } of series) {
    for (const point of card.trend) {
      const value = point.scorecard.metrics[def.key]?.value
      if (value === null || value === undefined) {
        continue
      }
      const row = rows.get(point.through) ?? { through: point.through }
      row[key] = value
      rows.set(point.through, row)
    }
  }
  const data = [...rows.values()].sort((a, b) => a.through - b.through)
  const config = Object.fromEntries(
    series.map(({ key, card }, index) => [
      key,
      {
        label: version(card.version.version_id),
        color: COLORS[index % COLORS.length],
      },
    ])
  ) satisfies ChartConfig
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{def.label}</p>
      {data.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          No finished runs yet.
        </p>
      ) : (
        <ChartContainer config={config} className="aspect-auto h-32 w-full">
          <LineChart
            data={data}
            margin={{ left: 4, right: 8, top: 4, bottom: 0 }}
          >
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="through"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickLine={false}
              axisLine={false}
              fontSize={10}
            />
            <YAxis
              hide
              domain={def.unit === "rate" ? [0, 1] : ["auto", "auto"]}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(_, payload) =>
                    `after ${payload[0]?.payload?.through ?? ""} runs`
                  }
                  formatter={(value, name) => (
                    <span className="flex w-full justify-between gap-3">
                      <span className="text-muted-foreground">
                        {config[String(name)]?.label ?? String(name)}
                      </span>
                      <span className="font-mono">
                        {metricText(
                          { key: def.key, value: Number(value), samples: 1 },
                          def
                        )}
                      </span>
                    </span>
                  )}
                />
              }
            />
            {series.map(({ key }) => (
              <Line
                key={key}
                dataKey={key}
                type="monotone"
                stroke={`var(--color-${key})`}
                strokeWidth={1.5}
                dot={{ r: 2 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ChartContainer>
      )}
    </div>
  )
}

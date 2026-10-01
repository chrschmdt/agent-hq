"use client"

import { Line, LineChart, XAxis, YAxis } from "recharts"

import { Badge } from "@/components/ui/badge"
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { Calibration, CriterionCalibration } from "@/lib/api/types"
import { percent } from "@/lib/format"

const DRIFT = {
  tpr: { label: "True positive rate", color: "var(--chart-1)" },
  tnr: { label: "True negative rate", color: "var(--chart-2)" },
} satisfies ChartConfig

function rate(value: number | null | undefined, interval: number[]): string {
  if (value === null || value === undefined) {
    return "-"
  }
  return `${percent(value)} (${percent(interval[0] ?? 0)} to ${percent(interval[1] ?? 1)})`
}

function Drift({ history }: { history: Calibration[] }) {
  if (history.length < 2) {
    return <span className="text-xs text-muted-foreground">-</span>
  }
  const data = history.map((point, index) => ({
    window: index + 1,
    tpr: point.tpr,
    tnr: point.tnr,
  }))
  return (
    <ChartContainer config={DRIFT} className="aspect-auto h-10 w-32">
      <LineChart data={data} margin={{ top: 2, bottom: 2, left: 2, right: 2 }}>
        <XAxis dataKey="window" hide />
        <YAxis hide domain={[0, 1]} />
        <ChartTooltip content={<ChartTooltipContent hideLabel />} />
        <Line
          dataKey="tpr"
          stroke="var(--color-tpr)"
          dot={false}
          strokeWidth={1.5}
        />
        <Line
          dataKey="tnr"
          stroke="var(--color-tnr)"
          dot={false}
          strokeWidth={1.5}
        />
      </LineChart>
    </ChartContainer>
  )
}

export function CalibrationView({
  report,
}: {
  report: CriterionCalibration[]
}) {
  const agents = [...new Set(report.map((item) => item.agent))]
  return (
    <div className="flex flex-col gap-6">
      {agents.map((agent) => (
        <div key={agent} className="flex flex-col gap-2">
          <h3 className="text-sm font-medium capitalize">{agent}</h3>
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[28%]">Criterion</TableHead>
                <TableHead className="w-[16%] text-right">Labels</TableHead>
                <TableHead className="w-[18%] text-right">
                  Finds real passes
                </TableHead>
                <TableHead className="w-[18%] text-right">
                  Finds real failures
                </TableHead>
                <TableHead className="w-[10%]">Counts</TableHead>
                <TableHead className="w-[10%]">Drift</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report
                .filter((item) => item.agent === agent)
                .map((item) => (
                  <TableRow key={item.criterion_id}>
                    <TableCell className="text-sm whitespace-normal">
                      {item.title}
                      {item.safety ? (
                        <Badge variant="outline" className="ml-2">
                          safety
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right text-xs tabular-nums">
                      {item.current.positives} pass, {item.current.negatives}{" "}
                      fail
                      {item.current.unknown
                        ? `, ${item.current.unknown} unknown`
                        : ""}
                    </TableCell>
                    <TableCell className="text-right text-xs tabular-nums">
                      {rate(item.current.tpr, item.current.tpr_interval)}
                    </TableCell>
                    <TableCell className="text-right text-xs tabular-nums">
                      {rate(item.current.tnr, item.current.tnr_interval)}
                    </TableCell>
                    <TableCell>
                      {item.current.calibrated ? (
                        <Badge
                          variant="outline"
                          className="border-transparent bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                        >
                          calibrated
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          not yet
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Drift history={item.history} />
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  )
}

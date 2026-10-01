import Link from "next/link"

import { Ago } from "@/components/ago"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { GuardrailSummary } from "@/lib/api/types"
import { words } from "@/lib/format"

export function GuardrailsView({ summary }: { summary: GuardrailSummary }) {
  const threats = Object.entries(summary.by_threat).sort(
    ([, a], [, b]) => b - a
  )
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <div>
          <div className="text-3xl font-semibold tabular-nums">
            {summary.inputs_blocked}
          </div>
          <p className="text-xs text-muted-foreground">
            messages held for a person by the input check
          </p>
        </div>
        <div>
          <div className="text-3xl font-semibold tabular-nums">
            {summary.replies_held}
          </div>
          <p className="text-xs text-muted-foreground">
            replies held back by the reply check
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {threats.map(([threat, count]) => (
            <Badge key={threat} variant="outline">
              {words(threat)}: {count}
            </Badge>
          ))}
        </div>
      </div>
      {summary.recent.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Nothing blocked yet.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Why</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {summary.recent.map((block, index) => (
              <TableRow key={`${block.work_item_id}-${index}`}>
                <TableCell className="text-xs">
                  {block.work_item_id ? (
                    <Link
                      href={`/runs/${block.work_item_id}`}
                      className="font-mono underline underline-offset-4"
                    >
                      {block.work_item_id}
                    </Link>
                  ) : (
                    "none"
                  )}
                  <div>
                    <Ago iso={block.at} />
                  </div>
                </TableCell>
                <TableCell className="text-xs">
                  {block.stage === "input"
                    ? `input, ${words(block.threat ?? "")}`
                    : "reply"}
                </TableCell>
                <TableCell className="max-w-xl text-xs whitespace-normal">
                  {block.reason}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

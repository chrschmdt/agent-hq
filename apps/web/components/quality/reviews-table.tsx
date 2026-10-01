import Link from "next/link"

import { Ago } from "@/components/ago"
import { VerdictBadge } from "@/components/quality/verdict-badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { ReviewRecord } from "@/lib/api/types"
import { usd, version, words } from "@/lib/format"

export function ReviewsTable({ reviews }: { reviews: ReviewRecord[] }) {
  if (reviews.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No reviews yet.
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead>
          <TableHead>Why</TableHead>
          <TableHead>Verdicts</TableHead>
          <TableHead className="text-right">Cost</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {reviews.map((review) => (
          <TableRow key={review.review_id}>
            <TableCell className="text-xs">
              <Link
                href={`/runs/${review.work_item_id}`}
                className="font-mono underline underline-offset-4"
              >
                {version(review.version_id)}
              </Link>
              <div>
                <Ago iso={review.created_at} />
              </div>
            </TableCell>
            <TableCell className="text-xs">{words(review.reason)}</TableCell>
            <TableCell className="whitespace-normal">
              <div className="flex max-w-xl flex-wrap gap-1">
                {review.criteria.map((criterion) => (
                  <span
                    key={criterion.criterion_id}
                    className="flex items-center gap-1 text-xs"
                    title={criterion.critique}
                  >
                    {words(criterion.criterion_id)}
                    <VerdictBadge verdict={criterion.verdict} />
                  </span>
                ))}
              </div>
            </TableCell>
            <TableCell className="text-right text-xs tabular-nums">
              {usd(review.cost_usd)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

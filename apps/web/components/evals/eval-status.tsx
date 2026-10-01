import { Badge } from "@/components/ui/badge"
import type { EvalStatus } from "@/lib/api/types"
import { cn } from "@/lib/utils"

const TONE: Record<EvalStatus, string> = {
  queued: "bg-muted",
  running: "bg-primary/10 text-primary",
  passed: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  failed: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  error: "bg-destructive/10 text-destructive",
}

export function EvalStatusBadge({ status }: { status: EvalStatus }) {
  return (
    <Badge variant="outline" className={cn("border-transparent", TONE[status])}>
      {status}
    </Badge>
  )
}

import { Badge } from "@/components/ui/badge"
import type { WorkStatus } from "@/lib/api/types"
import { words } from "@/lib/format"
import { cn } from "@/lib/utils"

const TONE: Partial<Record<WorkStatus, string>> = {
  running: "bg-primary/10 text-primary",
  waiting_approval: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  done: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  escalated: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  failed: "bg-destructive/10 text-destructive",
}

export function WorkStatusBadge({ status }: { status: WorkStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn("border-transparent", TONE[status] ?? "bg-muted")}
    >
      {words(status)}
    </Badge>
  )
}

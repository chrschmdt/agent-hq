import { Badge } from "@/components/ui/badge"
import type { VersionStatus } from "@/lib/api/types"
import { cn } from "@/lib/utils"

const TONE: Record<VersionStatus, string> = {
  live: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  canary: "bg-primary/10 text-primary",
  evaluated: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  draft: "bg-muted",
  retired: "bg-muted text-muted-foreground",
}

export function VersionStatusBadge({
  status,
  pct,
}: {
  status: VersionStatus
  pct?: number | null
}) {
  return (
    <Badge variant="outline" className={cn("border-transparent", TONE[status])}>
      {status === "canary" && pct ? `canary ${pct}%` : status}
    </Badge>
  )
}

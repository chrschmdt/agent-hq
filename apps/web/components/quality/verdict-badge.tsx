import { Badge } from "@/components/ui/badge"
import type { Verdict } from "@/lib/api/types"
import { cn } from "@/lib/utils"

const TONE: Record<Verdict, string> = {
  pass: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  fail: "bg-destructive/10 text-destructive",
  unknown: "bg-muted text-muted-foreground",
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <Badge
      variant="outline"
      className={cn("border-transparent", TONE[verdict])}
    >
      {verdict}
    </Badge>
  )
}

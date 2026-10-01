import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const TONE: Record<string, string> = {
  high: "bg-destructive/10 text-destructive",
  medium: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  low: "bg-muted text-muted-foreground",
}

export function Severity({ level }: { level: string }) {
  return (
    <Badge className={cn("border-transparent", TONE[level])}>{level}</Badge>
  )
}

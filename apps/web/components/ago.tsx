"use client"

import { useDay, useMoment } from "@/components/recording/recording-provider"
import { ago } from "@/lib/format"

export function Ago({ iso }: { iso: string }) {
  const moment = useMoment()
  const day = useDay()
  return (
    <time
      dateTime={iso}
      suppressHydrationWarning
      className="text-xs text-muted-foreground tabular-nums"
    >
      {ago(day(iso), moment ?? undefined)}
    </time>
  )
}

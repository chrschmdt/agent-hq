"use client"

import { usd } from "@/lib/format"
import type { Frame } from "@/lib/scene/frame"

export function CaptionLine({ frame }: { frame: Frame }) {
  return (
    <div className="flex min-h-6 flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
      <p className="text-sm" aria-live="polite">
        {frame.clock ? (
          <span className="mr-2 font-mono text-xs text-muted-foreground">
            {frame.clock}
          </span>
        ) : null}
        {frame.caption?.text ?? "Waiting for the first event."}
      </p>
      <p className="font-mono text-xs text-muted-foreground tabular-nums">
        {frame.totals.modelCalls} model calls · {frame.totals.toolCalls} tool
        calls · {usd(frame.totals.spent)}
      </p>
    </div>
  )
}

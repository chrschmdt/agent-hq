"use client"

import { useEffect, useRef, useState } from "react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { type Bar, foldedAxis, type Inspection } from "@/lib/inspector/passes"
import { cn } from "@/lib/utils"

const LABEL_WIDTH = 124
const LANE_HEIGHT = 30

const TONE: Record<Bar["tone"], string> = {
  triage: "bg-[color-mix(in_oklch,var(--map-live)_55%,var(--card))]",
  agent: "bg-[var(--map-live)]",
  tool: "bg-[color-mix(in_oklch,var(--map-live)_40%,var(--card))] ring-1 ring-[var(--map-live)]",
  refused: "bg-[var(--map-red)]",
  wait: "bg-[repeating-linear-gradient(135deg,var(--map-amber)_0_4px,transparent_4px_8px)] ring-1 ring-[var(--map-amber)]",
}

function seconds(ms: number): string {
  const s = ms / 1000
  return s >= 90
    ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
    : `${s.toFixed(s < 10 ? 1 : 0)} s`
}

export function TimelineCard({
  inspection,
  selected,
  onSelect,
}: {
  inspection: Inspection
  selected: string | null
  onSelect: (key: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  useEffect(() => {
    const element = ref.current
    if (!element) {
      return
    }
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(200, entry.contentRect.width - LABEL_WIDTH - 12))
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const axis = foldedAxis(inspection.lanes, width)
  const height = inspection.lanes.length * LANE_HEIGHT
  return (
    <Card>
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
        <CardDescription>
          Wall-clock time from the first event. Quiet stretches, such as a wait
          for you or for the customer, are folded. Click a bar to open its pass.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div ref={ref} className="relative" style={{ height: height + 26 }}>
          {inspection.lanes.map((lane, index) => (
            <div
              key={lane.key}
              className="absolute right-0 left-0"
              style={{ top: index * LANE_HEIGHT, height: LANE_HEIGHT }}
            >
              <span
                className="absolute top-1.5 left-0 truncate text-xs text-muted-foreground"
                style={{ width: LABEL_WIDTH - 8 }}
              >
                {lane.label}
              </span>
              <span
                className="absolute top-[15px] h-px bg-border"
                style={{ left: LABEL_WIDTH, right: 0 }}
              />
              {lane.bars.map((bar, barIndex) => {
                const left = axis.toX(bar.start)
                const barWidth = Math.max(3, axis.toX(bar.end) - left)
                const hot = bar.pass !== undefined && bar.pass === selected
                const dim = selected !== null && bar.pass !== undefined && !hot
                const style = { left: LABEL_WIDTH + left, width: barWidth }
                const className = cn(
                  "absolute top-[7px] h-4 rounded-[4px] transition-opacity",
                  TONE[bar.tone],
                  dim && "opacity-40",
                  hot && "outline-2 outline-offset-1 outline-foreground/60"
                )
                return bar.pass ? (
                  <button
                    key={barIndex}
                    type="button"
                    aria-label={`Open ${bar.pass}`}
                    onClick={() => onSelect(bar.pass ?? "")}
                    className={cn(className, "cursor-pointer")}
                    style={style}
                  />
                ) : (
                  <span key={barIndex} className={className} style={style} />
                )
              })}
              {lane.marks.map((mark, markIndex) => {
                const x = axis.toX(mark.at)
                const flip = x > width - 110
                return (
                  <span
                    key={markIndex}
                    className={cn(
                      "absolute top-[10px] flex items-center gap-1.5",
                      flip && "flex-row-reverse"
                    )}
                    style={
                      flip
                        ? { right: width - x + 7, left: "auto" }
                        : { left: LABEL_WIDTH + x - 5 }
                    }
                  >
                    <span className="size-2.5 rounded-full bg-[var(--map-reply)]" />
                    <span className="font-mono text-[11px] whitespace-nowrap text-muted-foreground">
                      {mark.label}
                    </span>
                  </span>
                )
              })}
            </div>
          ))}
          {axis.folds.map((fold, index) => (
            <span
              key={index}
              className="absolute border-x border-dashed bg-[repeating-linear-gradient(135deg,var(--border)_0_3px,transparent_3px_7px)]"
              style={{ left: LABEL_WIDTH + fold.x, width: 40, top: 0, height }}
            >
              <span
                className="absolute left-1/2 -translate-x-1/2 font-mono text-[10px] whitespace-nowrap text-muted-foreground"
                style={{ top: height + 6 }}
              >
                {seconds(fold.ms)}
              </span>
            </span>
          ))}
          <span
            className="absolute font-mono text-[10px] text-muted-foreground"
            style={{ left: LABEL_WIDTH, top: height + 6 }}
          >
            0 s
          </span>
          <span
            className="absolute right-0 font-mono text-[10px] text-muted-foreground"
            style={{ top: height + 6 }}
          >
            {seconds(inspection.duration)}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

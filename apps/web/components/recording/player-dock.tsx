"use client"

import { PauseIcon, PlayIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import Link from "next/link"

import { usePlayer, useSource } from "@/components/recording/recording-provider"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { usd } from "@/lib/format"
import { DAY_SPEEDS } from "@/lib/scene/day"
import { cn } from "@/lib/utils"

const MINUTE_MS = 60_000

function playsIn(length: number, speed: number): string {
  const minutes = Math.max(1, Math.round(length / speed / MINUTE_MS))
  return `The day in about ${minutes} minute${minutes === 1 ? "" : "s"}`
}

export function PlayerDock() {
  const source = useSource()
  const player = usePlayer()
  if (source.mode !== "recording" || !source.prepared || !player.frame) {
    return null
  }
  const { timeline } = source.prepared
  const frame = player.frame
  const day = player.day
  const length = day ? Math.max(MINUTE_MS, day.end - day.start) : 1
  const along = (t: number) => (day ? day.storeAt(t) - day.start : 0)
  return (
    <div className="sticky bottom-0 z-20 border-t bg-background/92 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-2 px-4 py-2.5 md:px-8">
        <div className="flex items-center gap-3">
          <Button
            size="icon"
            className="size-10 shrink-0 rounded-full"
            onClick={player.atEnd ? player.start : player.toggle}
            aria-label={player.playing ? "Pause" : "Play"}
          >
            <HugeiconsIcon
              icon={player.playing ? PauseIcon : PlayIcon}
              className="size-5"
            />
          </Button>
          <span
            className="w-16 shrink-0 font-mono text-sm tabular-nums"
            title="The store's time"
          >
            {frame.clock ?? "--:--"}
          </span>
          <div className="relative min-w-0 flex-1">
            {timeline.chapters.map((chapter) => (
              <span
                key={chapter.label}
                title={chapter.label}
                className="pointer-events-none absolute -top-0.5 h-2 w-px bg-muted-foreground/60"
                style={{ left: `${(along(chapter.at) / length) * 100}%` }}
              />
            ))}
            <label htmlFor="day-scrubber" className="sr-only">
              Position in the day
            </label>
            <input
              id="day-scrubber"
              type="range"
              min={0}
              max={length}
              step={MINUTE_MS}
              value={along(player.t)}
              onChange={(event) =>
                day &&
                player.seek(day.wallAt(day.start + Number(event.target.value)))
              }
              className="mt-1.5 w-full accent-[var(--map-live)]"
            />
          </div>
          <div
            className="flex shrink-0 items-center gap-1"
            role="group"
            aria-label="Speed"
          >
            {DAY_SPEEDS.map((speed) => (
              <Button
                key={speed}
                size="sm"
                variant={player.speed === speed ? "default" : "outline"}
                className="h-7 px-2 text-xs"
                title={playsIn(length, speed)}
                onClick={() => player.setSpeed(speed)}
              >
                {speed}x
              </Button>
            ))}
          </div>
          <label className="hidden shrink-0 items-center gap-2 text-xs text-muted-foreground lg:flex">
            <Switch
              checked={player.skipQuiet}
              onCheckedChange={player.setSkipQuiet}
            />
            Skip quiet stretches
          </label>
          {source.admin ? (
            <Button
              size="sm"
              variant="ghost"
              className="hidden shrink-0 sm:inline-flex"
              onClick={() => source.setMode("live")}
            >
              Back to live
            </Button>
          ) : null}
        </div>
        <div className="flex min-w-0 items-baseline gap-3 text-sm">
          <Link
            href="/overview"
            className="hidden shrink-0 text-xs font-medium text-[var(--map-live)] underline-offset-4 hover:underline md:inline"
          >
            {source.selected?.title ?? "Recorded day"}
          </Link>
          <p
            className={cn(
              "min-w-0 flex-1 truncate",
              frame.caption ? "" : "text-muted-foreground"
            )}
            aria-live="polite"
          >
            {player.atEnd && !player.playing
              ? "The day as it ended. Press play to watch it from the morning."
              : (frame.caption?.text ?? "The day begins.")}
          </p>
          <span className="hidden shrink-0 font-mono text-xs text-muted-foreground tabular-nums md:inline">
            {frame.totals.modelCalls} model calls · {frame.totals.toolCalls}{" "}
            tool calls · {usd(frame.totals.spent)}
          </span>
        </div>
      </div>
    </div>
  )
}

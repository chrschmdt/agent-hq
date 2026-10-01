"use client"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useLive } from "@/components/live/live-provider"
import { useRecorded } from "@/components/recording/recording-provider"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { LiveState } from "@/hooks/use-live-events"
import { FEED_LIMIT } from "@/lib/live/feed"
import { feedAt, storeTimeOf } from "@/lib/recording/derive"
import { cn } from "@/lib/utils"

import { EventRow } from "./event-row"

const STATE: Record<LiveState, { label: string; dot: string }> = {
  live: { label: "Live", dot: "bg-emerald-500 animate-pulse" },
  connecting: { label: "Reconnecting", dot: "bg-amber-500" },
  paused: {
    label: "Paused while the tab is hidden",
    dot: "bg-muted-foreground",
  },
  idle: {
    label: "Idle, streaming starts when work begins",
    dot: "bg-muted-foreground/50",
  },
}

export function LiveFeed({ liveOnly = false }: { liveOnly?: boolean }) {
  const live = useLive()
  const fromRecording = useRecorded((prepared, cursor) =>
    feedAt(prepared, cursor).map((event) => ({
      event,
      at: storeTimeOf(prepared, event),
    }))
  )
  const recorded = liveOnly
    ? { recording: false, data: undefined }
    : fromRecording
  const rows = recorded.recording
    ? (recorded.data ?? [])
    : live.events.map((event) => ({ event, at: undefined }))
  const indicator = recorded.recording
    ? {
        label: "The recorded day, up to the playback's moment",
        dot: "bg-[var(--map-live)]",
      }
    : STATE[live.state]
  return (
    <Card className="gap-0 overflow-hidden pb-0">
      <CardHeader className="border-b pb-4">
        <CardTitle>Event feed</CardTitle>
        <CardDescription className="flex items-center gap-2">
          <span className={cn("size-2 rounded-full", indicator.dot)} />
          {indicator.label}
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            {recorded.recording
              ? "Nothing has happened yet at this point of the day."
              : "No events yet. Start a simulated day to watch the team work."}
          </p>
        ) : (
          <ScrollArea className="h-[28rem]">
            <ul className="divide-y">
              {rows.slice(0, FEED_LIMIT).map(({ event, at }) => (
                <EventRow key={event.id} event={event} at={at} />
              ))}
            </ul>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
}

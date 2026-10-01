"use client"

import { useQueryClient } from "@tanstack/react-query"
import { createContext, useContext, useEffect, useRef } from "react"

import { type LiveState, useLiveEvents } from "@/hooks/use-live-events"
import type { AhqEvent, Status } from "@/lib/api/types"
import { queriesFor } from "@/lib/live/invalidate"

type Live = { events: AhqEvent[]; state: LiveState; status: Status | undefined }

const LiveContext = createContext<Live>({
  events: [],
  state: "idle",
  status: undefined,
})

const REFRESH_MS = 1500

export function LiveProvider({
  enabled,
  children,
}: {
  enabled: boolean
  children: React.ReactNode
}) {
  const live = useLiveEvents(enabled)
  const client = useQueryClient()
  const seen = useRef<number | null>(null)
  const pending = useRef(new Set<string>())
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const newest = live.events[0]?.id
    if (newest === undefined) {
      return
    }
    if (seen.current === null) {
      seen.current = newest
      return
    }
    const since = seen.current
    const fresh = live.events.filter((event) => event.id > since)
    if (fresh.length === 0) {
      return
    }
    seen.current = Math.max(since, ...fresh.map((event) => event.id))
    for (const event of fresh) {
      for (const key of queriesFor(event.kind)) {
        pending.current.add(key)
      }
    }
    if (timer.current === null && pending.current.size > 0) {
      timer.current = setTimeout(() => {
        for (const key of pending.current) {
          void client.invalidateQueries({ queryKey: [key] })
        }
        pending.current.clear()
        timer.current = null
      }, REFRESH_MS)
    }
  }, [live.events, client])

  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current)
      }
    },
    []
  )

  return <LiveContext value={live}>{children}</LiveContext>
}

export function useLive(): Live {
  return useContext(LiveContext)
}

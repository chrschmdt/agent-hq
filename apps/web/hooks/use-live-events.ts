"use client"

import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

import { api } from "@/lib/api/client"
import type { AhqEvent, Status } from "@/lib/api/types"
import { KEEP_LIMIT, latestCursor, mergeEvents } from "@/lib/live/feed"

import { usePageVisible } from "./use-page-visible"

export type LiveState = "live" | "connecting" | "paused" | "idle"

const STATUS_POLL_MS = 10_000
const LINGER_MS = 60_000
const RECENT = 200
const RETRY_MS = 5_000

async function fetchStatus(): Promise<Status> {
  const { data, error } = await api.GET("/api/status")
  if (error || !data) {
    throw new Error("could not load status")
  }
  return data
}

async function fetchRecent(): Promise<AhqEvent[]> {
  const last = (await fetchStatus()).last_event_id
  const { data, error } = await api.GET("/api/events", {
    params: { query: { after: Math.max(0, last - RECENT), limit: RECENT } },
  })
  if (error || !data) {
    throw new Error("could not load recent events")
  }
  return [...data].reverse()
}

export function useLiveEvents(enabled = true) {
  const visible = usePageVisible()
  const [events, setEvents] = useState<AhqEvent[]>([])
  const [loaded, setLoaded] = useState(false)
  const [state, setState] = useState<LiveState>("idle")
  const [lingerUntil, setLingerUntil] = useState(0)
  const cursor = useRef(0)

  useEffect(() => {
    if (!enabled) {
      return
    }
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () => {
      fetchRecent().then(
        (recent) => {
          if (stopped) {
            return
          }
          cursor.current = Math.max(cursor.current, latestCursor(recent))
          setEvents((current) => mergeEvents(current, recent, KEEP_LIMIT))
          setLoaded(true)
        },
        () => {
          if (!stopped) {
            timer = setTimeout(load, RETRY_MS)
          }
        }
      )
    }
    load()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [enabled])

  const status = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: visible ? STATUS_POLL_MS : false,
    enabled,
  })

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (lingerUntil <= now) {
      return
    }
    const timer = setTimeout(() => setNow(Date.now()), lingerUntil - now)
    return () => clearTimeout(timer)
  }, [lingerUntil, now])

  const hasActivity = Boolean(status.data?.active) || lingerUntil > now
  const shouldStream = enabled && loaded && visible && hasActivity

  useEffect(() => {
    if (!shouldStream) {
      return
    }
    const source = new EventSource(`/api/events/stream?after=${cursor.current}`)
    source.onopen = () => setState("live")
    source.onerror = () => setState("connecting")
    source.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as AhqEvent
      cursor.current = Math.max(cursor.current, event.id)
      setEvents((current) => mergeEvents(current, [event], KEEP_LIMIT))
      const until = Date.now() + LINGER_MS
      setLingerUntil(until)
      setNow(Date.now())
    }
    return () => {
      source.close()
    }
  }, [shouldStream])

  const shown: LiveState = !visible ? "paused" : shouldStream ? state : "idle"
  return { events, state: shown, status: status.data }
}

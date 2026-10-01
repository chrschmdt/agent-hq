"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { useLive } from "@/components/live/live-provider"
import type { Lineup } from "@/lib/api/types"
import { simulatedAt } from "@/lib/scene/frame"
import { buildTimeline, type Timeline } from "@/lib/scene/timeline"

const DELAY_MS = 1500
const FRAME_MS = 33
const LEAD_MS = 20_000
const NEW_DAY_MS = 60 * 60 * 1000
const GLIDE_MS = 400

export function useLiveScene(
  lineup: Lineup | undefined,
  running: boolean
): { timeline: Timeline; t: number; clock: number | null } {
  const { events } = useLive()
  const timeline = useMemo(
    () => buildTimeline(events, lineup),
    [events, lineup]
  )
  const latest = useRef(timeline)
  const skew = useRef<number | null>(null)
  const shown = useRef<number | null>(null)
  const [moment, setMoment] = useState<{ t: number; clock: number | null }>({
    t: 0,
    clock: null,
  })

  useEffect(() => {
    latest.current = timeline
  }, [timeline])

  useEffect(() => {
    const newest = events[0]
    if (newest?.recorded_at) {
      const estimate = Date.parse(newest.recorded_at) - Date.now()
      skew.current =
        skew.current === null ? estimate : Math.max(skew.current, estimate)
    }
  }, [events])

  useEffect(() => {
    if (!running) {
      return
    }
    let frame = 0
    let drawn = 0
    const step = (now: number) => {
      if (now - drawn >= FRAME_MS) {
        const glide = drawn === 0 ? 1 : Math.min(1, (now - drawn) / GLIDE_MS)
        drawn = now
        const current = latest.current
        const t = Date.now() + (skew.current ?? 0) - current.origin - DELAY_MS
        const sim = simulatedAt(current, t, LEAD_MS)
        const was = shown.current
        shown.current =
          sim === null || was === null || sim < was - NEW_DAY_MS
            ? sim
            : was + Math.max(0, sim - was) * glide
        setMoment({ t, clock: shown.current })
      }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [running])

  return { timeline, ...moment }
}

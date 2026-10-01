"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import type { DaySpeed } from "@/lib/scene/day"

const FRAME_MS = 33
const QUIET_MS = 2000
const LEAD_MS = 500

export type Course = {
  duration: number
  rate: (t: number, speed: number) => number
  realBetween: (from: number, to: number, speed: number) => number
}

export type Playback = {
  t: number
  playing: boolean
  speed: DaySpeed
  play: () => void
  pause: () => void
  toggle: () => void
  seek: (t: number) => void
  setSpeed: (speed: DaySpeed) => void
}

export function usePlayback(
  course: Course,
  initialSpeed: DaySpeed,
  skip?: (t: number) => number | null
): Playback {
  const { duration } = course
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<DaySpeed>(initialSpeed)
  const clock = useRef({ t: 0, last: 0, shown: 0 })

  useEffect(() => {
    if (!playing) {
      return
    }
    let frame = 0
    clock.current.last = performance.now()
    const step = (now: number) => {
      const state = clock.current
      const elapsed = now - state.last
      state.last = now
      state.t = Math.min(
        duration,
        state.t + elapsed * course.rate(state.t, speed)
      )
      const next = skip?.(state.t)
      if (
        next !== null &&
        next !== undefined &&
        course.realBetween(state.t, next, speed) > QUIET_MS
      ) {
        const lead = LEAD_MS * course.rate(Math.max(0, next - 1), speed)
        state.t = Math.min(duration, Math.max(state.t, next - lead))
      }
      if (now - state.shown >= FRAME_MS || state.t >= duration) {
        state.shown = now
        setT(state.t)
      }
      if (state.t >= duration) {
        setPlaying(false)
        return
      }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [playing, speed, duration, course, skip])

  const seek = useCallback(
    (to: number) => {
      const bounded = Math.min(duration, Math.max(0, to))
      clock.current.t = bounded
      setT(bounded)
    },
    [duration]
  )
  const play = useCallback(() => {
    if (clock.current.t >= duration) {
      clock.current.t = 0
      setT(0)
    }
    setPlaying(true)
  }, [duration])
  const pause = useCallback(() => setPlaying(false), [])
  const toggle = useCallback(
    () => (playing ? pause() : play()),
    [playing, pause, play]
  )

  return { t, playing, speed, play, pause, toggle, seek, setSpeed }
}

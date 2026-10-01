"use client"

import { useQuery } from "@tanstack/react-query"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"

import { type Course, type Playback, usePlayback } from "@/hooks/use-playback"
import type { RecordingInfo } from "@/lib/api/types"
import { clock } from "@/lib/format"
import {
  cursorAt,
  momentOf,
  type Prepared,
  prepare,
} from "@/lib/recording/derive"
import { loadRecording } from "@/lib/recording/load"
import { type DayAxis, dayAxis } from "@/lib/scene/day"
import { type Frame, frameAt } from "@/lib/scene/frame"
import { nextActivity } from "@/lib/scene/timeline"

export type Mode = "live" | "recording"

type Source = {
  admin: boolean
  mode: Mode
  setMode: (mode: Mode) => void
  recordings: RecordingInfo[]
  selected: RecordingInfo | null
  select: (id: string) => void
  prepared: Prepared | null
  loading: boolean
  failed: boolean
}

type Player = Playback & {
  duration: number
  day: DayAxis | null
  frame: Frame | null
  atEnd: boolean
  skipQuiet: boolean
  setSkipQuiet: (skip: boolean) => void
  start: () => void
}

const SourceContext = createContext<Source | null>(null)
const PlayerContext = createContext<Player | null>(null)
const CursorContext = createContext(0)
const MomentContext = createContext<number | null>(null)
const DayContext = createContext<(iso: string) => string>((iso) => iso)

const DEFAULT_SPEED = 240
const IDLE: Course = {
  duration: 0,
  rate: () => 1,
  realBetween: (from, to) => to - from,
}

const CURSOR_MS = 250
const MODE_KEY = "ahq.mode"
const CHOICE_KEY = "ahq.recording"

const listeners = new Set<() => void>()
const fallback = new Map<string, string>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function stored(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key) ?? fallback.get(key) ?? null
  } catch {
    return fallback.get(key) ?? null
  }
}

function store(key: string, value: string): void {
  fallback.set(key, value)
  try {
    window.sessionStorage.setItem(key, value)
  } catch {}
  for (const listener of listeners) {
    listener()
  }
}

function useStored(key: string): [string | null, (value: string) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => stored(key),
    () => null
  )
  const set = useCallback((next: string) => store(key, next), [key])
  return [value, set]
}

export function RecordingProvider({
  admin,
  recordings,
  children,
}: {
  admin: boolean
  recordings: RecordingInfo[]
  children: React.ReactNode
}) {
  const [adminMode, setAdminMode] = useStored(MODE_KEY)
  const [choice, select] = useStored(CHOICE_KEY)
  const mode: Mode = admin && adminMode !== "recording" ? "live" : "recording"
  const setMode = useCallback(
    (next: Mode) => setAdminMode(next),
    [setAdminMode]
  )
  const selected =
    recordings.find((info) => info.id === choice) ?? recordings[0] ?? null

  const loaded = useQuery({
    queryKey: ["recording", selected?.id],
    queryFn: () => loadRecording(selected?.id ?? ""),
    enabled: mode === "recording" && selected !== null,
    staleTime: Infinity,
    retry: 1,
  })
  const prepared = useMemo(
    () => (loaded.data ? prepare(loaded.data) : null),
    [loaded.data]
  )

  const [skipQuiet, setSkipQuiet] = useState(true)
  const skip = useCallback(
    (t: number) => (prepared ? nextActivity(prepared.timeline, t) : null),
    [prepared]
  )
  const duration = prepared?.timeline.duration ?? 0
  const day = useMemo(
    () => (prepared ? dayAxis(prepared.timeline) : null),
    [prepared]
  )
  const course = useMemo<Course>(
    () =>
      day ? { duration, rate: day.rate, realBetween: day.realBetween } : IDLE,
    [day, duration]
  )
  const playback = usePlayback(
    course,
    DEFAULT_SPEED,
    skipQuiet ? skip : undefined
  )
  const { seek } = playback
  useEffect(() => {
    if (prepared) {
      seek(prepared.timeline.duration)
    }
  }, [prepared, seek])

  const target = prepared ? cursorAt(prepared, playback.t) : 0
  const [cursor, setCursor] = useState(0)
  const latest = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSet = useRef(0)
  useEffect(() => {
    latest.current = target
    if (target === cursor || timer.current !== null) {
      return
    }
    const wait = playback.playing
      ? Math.max(0, CURSOR_MS - (performance.now() - lastSet.current))
      : 0
    timer.current = setTimeout(() => {
      timer.current = null
      lastSet.current = performance.now()
      setCursor(latest.current)
    }, wait)
  }, [target, cursor, playback.playing])
  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current)
      }
    },
    []
  )

  const showing = mode === "recording" && prepared !== null
  const drawn = showing ? frameAt(prepared.timeline, playback.t) : null
  const frame =
    drawn && day
      ? {
          ...drawn,
          clock: clock(new Date(day.storeAt(playback.t)).toISOString()),
        }
      : drawn
  const toDay = useMemo(
    () =>
      showing && day
        ? (iso: string) => new Date(day.toStore(Date.parse(iso))).toISOString()
        : (iso: string) => iso,
    [showing, day]
  )
  const { play } = playback
  const start = useCallback(() => {
    seek(0)
    play()
  }, [seek, play])

  const source = useMemo<Source>(
    () => ({
      admin,
      mode,
      setMode,
      recordings,
      selected,
      select,
      prepared: mode === "recording" ? prepared : null,
      loading: mode === "recording" && selected !== null && loaded.isPending,
      failed: loaded.isError,
    }),
    [
      admin,
      mode,
      setMode,
      recordings,
      selected,
      select,
      prepared,
      loaded.isPending,
      loaded.isError,
    ]
  )
  const player: Player = {
    ...playback,
    duration,
    day: showing ? day : null,
    frame,
    atEnd: duration > 0 && playback.t >= duration,
    skipQuiet,
    setSkipQuiet,
    start,
  }

  return (
    <SourceContext value={source}>
      <PlayerContext value={player}>
        <CursorContext value={showing ? cursor : 0}>
          <MomentContext
            value={
              showing && day ? day.toStore(momentOf(prepared, cursor)) : null
            }
          >
            <DayContext value={toDay}>{children}</DayContext>
          </MomentContext>
        </CursorContext>
      </PlayerContext>
    </SourceContext>
  )
}

export function useSource(): Source {
  const source = useContext(SourceContext)
  if (source === null) {
    throw new Error("useSource needs a RecordingProvider")
  }
  return source
}

export function usePlayer(): Player {
  const player = useContext(PlayerContext)
  if (player === null) {
    throw new Error("usePlayer needs a RecordingProvider")
  }
  return player
}

export function useMoment(): number | null {
  return useContext(MomentContext)
}

export function useDaySpan(): (from: number, to: number) => number {
  const day = useContext(DayContext)
  return useCallback(
    (from: number, to: number) =>
      Date.parse(day(new Date(to).toISOString())) -
      Date.parse(day(new Date(from).toISOString())),
    [day]
  )
}

export function useDay(): (iso: string) => string {
  return useContext(DayContext)
}

export function useRecorded<T>(
  view: (prepared: Prepared, cursor: number) => T
): {
  recording: boolean
  data: T | undefined
} {
  const { mode, prepared } = useSource()
  const cursor = useContext(CursorContext)
  const data = prepared ? view(prepared, cursor) : undefined
  return { recording: mode === "recording", data }
}

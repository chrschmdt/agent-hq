"use client"

import { useLive } from "@/components/live/live-provider"
import { useRecorded } from "@/components/recording/recording-provider"
import type { Status } from "@/lib/api/types"
import { statusAt } from "@/lib/recording/derive"

export function useStatus(): Status | undefined {
  const { status } = useLive()
  const recorded = useRecorded(statusAt)
  return recorded.recording ? recorded.data : status
}

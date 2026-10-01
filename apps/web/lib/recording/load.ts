import type { Recording, RecordingInfo } from "@/lib/api/types"

export const RECORDING_VERSION = 2

export async function loadRecording(id: string): Promise<Recording> {
  const response = await fetch(`/api/recordings/${encodeURIComponent(id)}`)
  if (!response.ok) {
    throw new Error(`could not load recording ${id}`)
  }
  const recording = (await response.json()) as Recording
  if (recording.version !== RECORDING_VERSION) {
    throw new Error(`recording ${id} is in an older format`)
  }
  return recording
}

export function realModels(info: RecordingInfo): boolean {
  return info.summary.profile !== "mock"
}

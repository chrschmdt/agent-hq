import type { Passage, SearchResult } from "@/lib/api/types"

export const STAGES = ["dense", "bm25", "fused", "reranked"] as const
export type Stage = (typeof STAGES)[number]

export const STAGE_LABELS: Record<Stage, string> = {
  dense: "Dense",
  bm25: "BM25",
  fused: "Fused (RRF)",
  reranked: "Reranked",
}

export type Line = {
  passageId: string
  ranks: (number | null)[]
  final: boolean
}

export function topIds(
  result: SearchResult,
  stage: Stage,
  depth: number
): string[] {
  const trace = result.trace
  if (!trace) {
    return []
  }
  return trace[stage].slice(0, depth).map((ranked) => ranked.passage_id)
}

export function bumpLines(result: SearchResult, depth = 10): Line[] {
  const tops = STAGES.map((stage) => topIds(result, stage, depth))
  const final = new Set(result.passages.map((passage) => passage.passage_id))
  const ids = [...new Set(tops.flat())]
  return ids.map((passageId) => ({
    passageId,
    ranks: tops.map((ids) => {
      const index = ids.indexOf(passageId)
      return index === -1 ? null : index + 1
    }),
    final: final.has(passageId),
  }))
}

export function passagesById(result: SearchResult): Map<string, Passage> {
  const passages = [...(result.trace?.candidates ?? []), ...result.passages]
  return new Map(passages.map((passage) => [passage.passage_id, passage]))
}

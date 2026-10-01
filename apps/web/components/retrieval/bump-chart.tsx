"use client"

import { type Line, STAGE_LABELS, STAGES } from "@/lib/retrieval"
import { cn } from "@/lib/utils"

const WIDTH = 640
const ROW = 28
const LEFT = 40
const RIGHT = 40

export function BumpChart({
  lines,
  depth,
  selected,
  onSelect,
}: {
  lines: Line[]
  depth: number
  selected: string | null
  onSelect: (passageId: string) => void
}) {
  const height = ROW * (depth + 1)
  const x = (stage: number) =>
    LEFT + (stage * (WIDTH - LEFT - RIGHT)) / (STAGES.length - 1)
  const y = (rank: number) => ROW * rank
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height + 16}`}
      role="img"
      aria-label="How each passage's rank changes across the four search stages"
      className="w-full text-muted-foreground"
    >
      {STAGES.map((stage, index) => (
        <text
          key={stage}
          x={x(index)}
          y={12}
          textAnchor="middle"
          className="fill-current text-[11px]"
        >
          {STAGE_LABELS[stage]}
        </text>
      ))}
      {Array.from({ length: depth }, (_, rank) => (
        <text
          key={rank}
          x={8}
          y={y(rank + 1) + 4}
          className="fill-current text-[10px]"
        >
          {rank + 1}
        </text>
      ))}
      {lines.map((line) => {
        const points = line.ranks
          .map((rank, stage) =>
            rank === null ? null : `${x(stage)},${y(rank)}`
          )
          .filter((point): point is string => point !== null)
        const strong = line.final || line.passageId === selected
        return (
          <g
            key={line.passageId}
            onClick={() => onSelect(line.passageId)}
            className={cn(
              "cursor-pointer",
              strong ? "text-primary" : "text-muted-foreground/40"
            )}
          >
            <polyline
              points={points.join(" ")}
              fill="none"
              stroke="currentColor"
              strokeWidth={line.passageId === selected ? 3 : strong ? 2 : 1}
            />
            {line.ranks.map((rank, stage) =>
              rank === null ? null : (
                <circle
                  key={stage}
                  cx={x(stage)}
                  cy={y(rank)}
                  r={4}
                  fill="currentColor"
                />
              )
            )}
          </g>
        )
      })}
    </svg>
  )
}

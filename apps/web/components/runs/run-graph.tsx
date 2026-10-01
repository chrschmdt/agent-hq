"use client"

import "@xyflow/react/dist/base.css"

import {
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react"

import type { PathStep, Topology, WorkStatus } from "@/lib/api/types"
import { runRoute, travelled } from "@/lib/flow/run"
import { cn } from "@/lib/utils"

type Stop = { label: string; visited: boolean; steps: number[]; kind: string }
type StopNode = Node<Stop, "stop">

const PLACES: Record<string, { column: number; y: number }> = {
  __start__: { column: 0, y: 140 },
  entry: { column: 1, y: 140 },
  screen: { column: 2, y: 140 },
  dispatcher: { column: 3, y: 140 },
  support: { column: 4, y: 20 },
  ops: { column: 4, y: 140 },
  insights: { column: 5, y: 260 },
  human: { column: 6, y: 260 },
  finalize: { column: 7, y: 140 },
  __end__: { column: 8, y: 140 },
}

const LABELS: Record<string, string> = {
  __start__: "start",
  __end__: "end",
  screen: "input check",
}

const MAX_PILLS = 4
const GAP = 56

function pills(steps: number[]): string[] {
  return steps.length > MAX_PILLS
    ? [
        ...steps.slice(0, MAX_PILLS - 1).map(String),
        `+${steps.length - MAX_PILLS + 1}`,
      ]
    : steps.map(String)
}

function widthOf(label: string, shown: number): number {
  return 28 + label.length * 7.5 + shown * 24
}

function StopView({ data }: NodeProps<StopNode>) {
  const terminal = data.kind === "start" || data.kind === "end"
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 border px-3 py-1.5 text-xs whitespace-nowrap",
        terminal ? "rounded-full" : "rounded-lg",
        data.visited
          ? "border-primary bg-primary/10 font-medium text-foreground"
          : "bg-card text-muted-foreground"
      )}
      title={
        data.steps.length > 0
          ? `${data.label}: step${data.steps.length === 1 ? "" : "s"} ${data.steps.join(", ")}`
          : undefined
      }
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <span>{data.label}</span>
      {pills(data.steps).map((pill) => (
        <span
          key={pill}
          className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground tabular-nums"
        >
          {pill}
        </span>
      ))}
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  )
}

const NODE_TYPES = { stop: StopView }

export function RunGraph({
  topology,
  path,
  status,
}: {
  topology: Topology
  path: PathStep[]
  status: WorkStatus
}) {
  const route = runRoute(path, status)
  const edgesTravelled = travelled(route)
  const steps = new Map<string, number[]>()
  path.forEach((step, index) =>
    steps.set(step.node, [...(steps.get(step.node) ?? []), index + 1])
  )
  const widest = new Map<number, number>()
  for (const node of topology.nodes) {
    const column = PLACES[node.id]?.column ?? 0
    const width = widthOf(
      LABELS[node.id] ?? node.id,
      pills(steps.get(node.id) ?? []).length
    )
    widest.set(column, Math.max(widest.get(column) ?? 0, width))
  }
  const lefts: number[] = []
  let x = 0
  for (let column = 0; column <= Math.max(...widest.keys()); column++) {
    lefts.push(x)
    x += (widest.get(column) ?? 0) + GAP
  }
  const nodes: StopNode[] = topology.nodes.map((node) => {
    const place = PLACES[node.id] ?? { column: 0, y: 0 }
    return {
      id: node.id,
      type: "stop",
      position: { x: lefts[place.column], y: place.y },
      data: {
        label: LABELS[node.id] ?? node.id,
        visited: route.includes(node.id),
        steps: steps.get(node.id) ?? [],
        kind: node.kind,
      },
      draggable: false,
    }
  })
  const edges: Edge[] = topology.edges.map((edge) => {
    const used = edgesTravelled.has(`${edge.source}->${edge.target}`)
    return {
      id: `${edge.source}->${edge.target}`,
      source: edge.source,
      target: edge.target,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: {
        stroke: used ? "var(--primary)" : "var(--muted-foreground)",
        strokeWidth: used ? 2 : 1,
        strokeDasharray: edge.conditional && !used ? "4 4" : undefined,
        opacity: used ? 1 : 0.3,
      },
    }
  })
  return (
    <div className="h-56 w-full rounded-xl border bg-muted/20">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
      />
    </div>
  )
}

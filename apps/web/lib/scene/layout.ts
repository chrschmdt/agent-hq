import type { Point, Polyline } from "./geometry"

export const CANVAS = { width: 1360, height: 780 }
export const COMPACT = { x: 296, width: 780 }

export type NodeId =
  | "customers"
  | "store"
  | "screen"
  | "dispatcher"
  | "support"
  | "ops"
  | "insights"
  | "you"
  | "qa"

export type StoreId = "orders" | "knowledge" | "analytics" | "cache"

export type Box = { x: number; y: number; w: number; h: number }

export const NODES: Record<NodeId, Box> = {
  customers: { x: 450, y: 52, w: 220, h: 64 },
  store: { x: 710, y: 52, w: 220, h: 64 },
  screen: { x: 430, y: 166, w: 500, h: 44 },
  dispatcher: { x: 580, y: 254, w: 200, h: 64 },
  support: { x: 330, y: 376, w: 200, h: 84 },
  ops: { x: 580, y: 376, w: 200, h: 84 },
  insights: { x: 830, y: 376, w: 200, h: 84 },
  you: { x: 560, y: 516, w: 240, h: 64 },
  qa: { x: 580, y: 664, w: 200, h: 56 },
}

export const AGENTS = ["support", "ops", "insights"] as const
export type AgentNode = (typeof AGENTS)[number]

export function isAgent(node: string): node is AgentNode {
  return (AGENTS as readonly string[]).includes(node)
}

export const PARK: Record<NodeId, Point> = {
  customers: [560, 116],
  store: [930, 84],
  screen: [560, 166],
  dispatcher: [680, 254],
  support: [430, 376],
  ops: [680, 376],
  insights: [930, 376],
  you: [680, 516],
  qa: [580, 692],
}

export const RAIL = {
  left: { x: 8, y: 16, w: 272, h: 748 },
  right: { x: 1080, y: 16, w: 272, h: 748 },
}

const ROW_TOP = 58
const ROW_STEP = 86
export const ROW = { x: 16, w: 248, h: 76 }

export function modelRow(index: number): Box {
  return { x: ROW.x, y: ROW_TOP + index * ROW_STEP, w: ROW.w, h: ROW.h }
}

export const STORES: Record<StoreId, Box> = {
  orders: { x: 1096, y: ROW_TOP, w: ROW.w, h: ROW.h },
  knowledge: { x: 1096, y: ROW_TOP + ROW_STEP, w: ROW.w, h: ROW.h },
  analytics: { x: 1096, y: ROW_TOP + 2 * ROW_STEP, w: ROW.w, h: ROW.h },
  cache: { x: 1096, y: ROW_TOP + 3 * ROW_STEP, w: ROW.w, h: ROW.h },
}

export const MODEL_ANCHOR: Partial<Record<NodeId, Point>> = {
  customers: [450, 78],
  screen: [430, 188],
  dispatcher: [580, 286],
  support: [330, 408],
  ops: [580, 404],
  insights: [830, 398],
  you: [560, 568],
  qa: [580, 692],
}

export const TOOL_ANCHOR: Partial<Record<NodeId, Point>> = {
  support: [530, 400],
  ops: [780, 404],
  insights: [1030, 404],
  you: [800, 548],
}

export function rowEdge(box: Box, side: "left" | "right"): Point {
  return [side === "left" ? box.x + box.w : box.x, box.y + box.h / 2]
}

const ROUTES: Record<string, Polyline> = {
  "customers>screen": [
    [560, 116],
    [560, 166],
  ],
  "screen>dispatcher": [
    [560, 166],
    [560, 232],
    [680, 232],
    [680, 254],
  ],
  "screen>support": [
    [560, 166],
    [520, 166],
    [520, 343],
    [430, 343],
    [430, 376],
  ],
  "screen>you": [
    [560, 166],
    [560, 188],
    [1060, 188],
    [1060, 500],
    [680, 500],
    [680, 516],
  ],
  "store>dispatcher": [
    [930, 84],
    [1045, 84],
    [1045, 238],
    [680, 238],
    [680, 254],
  ],
  "dispatcher>support": [
    [680, 254],
    [680, 343],
    [430, 343],
    [430, 376],
  ],
  "dispatcher>ops": [
    [680, 254],
    [680, 376],
  ],
  "dispatcher>insights": [
    [680, 254],
    [680, 343],
    [930, 343],
    [930, 376],
  ],
  "dispatcher>you": [
    [680, 254],
    [680, 343],
    [1060, 343],
    [1060, 500],
    [680, 500],
    [680, 516],
  ],
  "support>you": [
    [430, 376],
    [430, 498],
    [680, 498],
    [680, 516],
  ],
  "ops>you": [
    [680, 376],
    [680, 516],
  ],
  "insights>you": [
    [930, 376],
    [930, 498],
    [680, 498],
    [680, 516],
  ],
  "ops>insights": [
    [680, 376],
    [760, 418],
    [850, 418],
    [930, 376],
  ],
  "support>dispatcher": [
    [430, 376],
    [470, 300],
    [580, 300],
    [680, 254],
  ],
  "support>qa": [
    [360, 460],
    [360, 692],
    [580, 692],
  ],
  "ops>qa": [
    [680, 460],
    [680, 470],
    [990, 470],
    [990, 692],
    [780, 692],
  ],
  "insights>qa": [
    [990, 460],
    [990, 692],
    [780, 692],
  ],
  "dispatcher>qa": [
    [780, 286],
    [1060, 286],
    [1060, 692],
    [780, 692],
  ],
  "support>customers": [
    [330, 408],
    [312, 408],
    [312, 84],
    [450, 84],
  ],
  "customers>support": [
    [520, 116],
    [520, 166],
    [520, 343],
    [430, 343],
    [430, 376],
  ],
  "customers>ops": [
    [520, 116],
    [520, 343],
    [680, 343],
    [680, 376],
  ],
  "customers>insights": [
    [520, 116],
    [520, 343],
    [930, 343],
    [930, 376],
  ],
}

export function route(from: NodeId, to: NodeId): Polyline {
  const known = ROUTES[`${from}>${to}`]
  if (known) {
    return known
  }
  const back = ROUTES[`${to}>${from}`]
  if (back) {
    return [...back].reverse()
  }
  return [PARK[from], PARK[to]]
}

export type Edge = { d: string; lane?: boolean }

export const EDGES: Edge[] = [
  { d: "M560 116 V166" },
  { d: "M520 116 V166", lane: true },
  { d: "M560 210 V232 H680 V254" },
  { d: "M520 210 V343", lane: true },
  { d: "M930 84 H1045 V238 H680 V254", lane: true },
  {
    d: "M680 318 V343 M430 343 H930 M430 343 V376 M680 343 V376 M930 343 V376",
  },
  { d: "M780 418 H826" },
  { d: "M430 460 V498 H680 V516 M680 460 V516 M930 460 V498 H680" },
  { d: "M330 408 H312 V84 H450", lane: true },
  { d: "M360 460 V692 H580", lane: true },
  { d: "M990 460 V692 H780", lane: true },
  { d: "M930 188 H1060 V500 H800", lane: true },
]

export const HEADS: string[] = [
  "M555 158 L560 166 L565 158 Z",
  "M675 246 L680 254 L685 246 Z",
  "M425 368 L430 376 L435 368 Z",
  "M675 368 L680 376 L685 368 Z",
  "M925 368 L930 376 L935 368 Z",
  "M675 508 L680 516 L685 508 Z",
  "M822 413 L830 418 L822 423 Z",
  "M442 79 L450 84 L442 89 Z",
  "M572 687 L580 692 L572 697 Z",
  "M788 687 L780 692 L788 697 Z",
]

export type Label = { x: number; y: number; text: string; rotate?: number }

export const LABELS: Label[] = [
  { x: 784, y: 410, text: "handoff" },
  { x: 306, y: 330, text: "replies to customers", rotate: -90 },
  { x: 1054, y: 96, text: "alerts skip the check", rotate: 90 },
  { x: 514, y: 330, text: "follow-ups", rotate: -90 },
  { x: 368, y: 684, text: "finished runs" },
  { x: 1068, y: 360, text: "to a person", rotate: 90 },
]

export const TAG_AT: Partial<Record<NodeId, Point>> = {
  support: [332, 466],
  ops: [582, 466],
  insights: [832, 466],
  you: [806, 586],
}

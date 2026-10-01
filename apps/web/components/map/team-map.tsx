"use client"

import Link from "next/link"
import { type CSSProperties, useEffect, useRef, useState } from "react"

import type { AgentSummary } from "@/lib/api/types"
import { curvePath } from "@/lib/scene/geometry"
import type { Dot, Frame, NodeTone, NodeView } from "@/lib/scene/frame"
import {
  type Box,
  CANVAS,
  COMPACT,
  EDGES,
  HEADS,
  LABELS,
  modelRow,
  type NodeId,
  NODES,
  RAIL,
  STORES,
  type StoreId,
} from "@/lib/scene/layout"
import type { PacketStatus } from "@/lib/scene/timeline"
import { cn } from "@/lib/utils"
import { version } from "@/lib/format"

const COMPACT_BELOW = 720

const MODEL_TITLES: Record<string, string> = {
  "claude-haiku-4-5": "Haiku 4.5",
  "claude-sonnet-5": "Sonnet 5",
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-opus-5-5": "Opus 5.5",
  fake: "rules",
}

const DOT_COLOR: Record<Dot["tone"], string> = {
  ticket: "var(--map-live)",
  message: "var(--map-live)",
  alert: "var(--map-amber)",
  proposal: "var(--map-amber)",
  flag: "var(--map-violet)",
  review: "var(--map-violet)",
  attack: "var(--map-red)",
  reply: "var(--map-reply)",
  background: "var(--map-line)",
}

const PACKET_COLOR: Record<PacketStatus, string> = {
  ok: "var(--map-live)",
  cached: "var(--map-live)",
  refused: "var(--map-red)",
  failed: "var(--map-red)",
  waiting: "var(--map-amber)",
}

const TONE_COLOR: Record<Exclude<NodeTone, "idle">, string> = {
  live: "var(--map-live)",
  amber: "var(--map-amber)",
  red: "var(--map-red)",
}

const STORE_TEXT: Record<StoreId, { title: string; sub: string }> = {
  orders: { title: "Orders", sub: "store database, Postgres" },
  knowledge: { title: "Knowledge", sub: "Qdrant, published and pending" },
  analytics: { title: "Analytics", sub: "read-only Postgres role" },
  cache: { title: "Read cache", sub: "catalog reads and searches" },
}

function glow(tone: NodeTone): CSSProperties {
  if (tone === "idle") {
    return {}
  }
  const color = TONE_COLOR[tone]
  return {
    borderColor: color,
    boxShadow: `0 0 0 3px color-mix(in oklch, ${color} 16%, transparent), 0 0 26px color-mix(in oklch, ${color} 22%, transparent)`,
  }
}

function place(box: Box): CSSProperties {
  return { left: box.x, top: box.y, width: box.w, height: box.h }
}

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element) {
      return
    }
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width)
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

function StatusDot({ view }: { view: NodeView }) {
  const color =
    view.tone !== "idle"
      ? TONE_COLOR[view.tone]
      : view.busy
        ? "var(--map-live)"
        : "var(--map-idle)"
  return (
    <span
      className="size-2 shrink-0 rounded-full"
      style={{ background: color }}
    />
  )
}

function NodeCard({
  id,
  view,
  title,
  tag,
  sub,
  href,
}: {
  id: NodeId
  view: NodeView
  title: string
  tag?: string
  sub?: string
  href?: string
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <StatusDot view={view} />
          <span className="truncate text-[15px] font-semibold">{title}</span>
        </span>
        {tag ? (
          <span className="truncate font-mono text-[11px] text-muted-foreground">
            {tag}
          </span>
        ) : null}
        {!tag && view.cost ? (
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            {view.cost}
          </span>
        ) : null}
      </div>
      {sub ? (
        <div className="truncate font-mono text-[11px] text-muted-foreground">
          {sub}
        </div>
      ) : null}
      <div className="truncate font-mono text-[11px] tabular-nums">
        {view.stat}
        {tag && view.cost ? ` · ${view.cost}` : ""}
      </div>
    </>
  )
  const className =
    "absolute flex flex-col justify-center gap-1 rounded-xl border bg-card px-3 py-2 text-card-foreground transition-[border-color,box-shadow] duration-300"
  const style = { ...place(NODES[id]), ...glow(view.tone) }
  return href ? (
    <Link
      href={href}
      className={cn(className, "hover:bg-muted/40")}
      style={style}
      aria-label={`${title}: ${view.stat}`}
    >
      {body}
    </Link>
  ) : (
    <div className={className} style={style}>
      {body}
    </div>
  )
}

export function TeamMap({
  frame,
  agents,
  onPick,
}: {
  frame: Frame
  agents?: AgentSummary[]
  onPick?: (workItemId: string) => void
}) {
  const [ref, width] = useWidth()
  const compact = width > 0 && width < COMPACT_BELOW
  const logicalWidth = compact ? COMPACT.width : CANVAS.width
  const scale = width > 0 ? width / logicalWidth : 1
  const agent = (name: string) => {
    const found = agents?.find((a) => a.name === name)
    return found
      ? `${version(found.version)}, ${MODEL_TITLES[found.model] ?? found.model}`
      : undefined
  }
  const model = (name: string) => {
    const found = agents?.find((a) => a.name === name)
    return found ? (MODEL_TITLES[found.model] ?? found.model) : undefined
  }
  const { nodes } = frame

  return (
    <div
      ref={ref}
      className="relative w-full overflow-hidden"
      style={{ height: CANVAS.height * scale }}
    >
      <div
        className="absolute top-0 left-0 origin-top-left"
        style={{
          width: CANVAS.width,
          height: CANVAS.height,
          transform: `scale(${scale}) translateX(${compact ? -COMPACT.x : 0}px)`,
        }}
      >
        {compact ? null : (
          <>
            <div
              className="absolute rounded-xl border border-dashed bg-muted/20"
              style={place({ ...RAIL.left })}
            />
            <div
              className="absolute rounded-xl border border-dashed bg-muted/20"
              style={place({ ...RAIL.right })}
            />
            <div
              className="absolute flex items-baseline gap-2"
              style={{ left: 24, top: 28 }}
            >
              <span className="font-mono text-[11px] tracking-widest text-muted-foreground">
                MODELS
              </span>
              <span className="text-xs text-muted-foreground/80">
                through OpenRouter
              </span>
            </div>
            <div
              className="absolute flex items-baseline gap-2"
              style={{ left: 1096, top: 28 }}
            >
              <span className="font-mono text-[11px] tracking-widest text-muted-foreground">
                TOOLS AND DATA
              </span>
              <span className="text-xs text-muted-foreground/80">
                MCP servers
              </span>
            </div>
          </>
        )}

        <svg
          width={CANVAS.width}
          height={CANVAS.height}
          className="absolute top-0 left-0"
          aria-hidden
        >
          {compact
            ? null
            : frame.wires.map((wire) => (
                <path
                  key={wire.key}
                  className="map-wire"
                  data-state={wire.state}
                  d={curvePath(wire.path)}
                />
              ))}
          {EDGES.map((edge) => (
            <path
              key={edge.d}
              className={edge.lane ? "map-lane" : "map-edge"}
              d={edge.d}
            />
          ))}
          {HEADS.map((head) => (
            <path key={head} className="map-head" d={head} />
          ))}
          {LABELS.map((label) => (
            <text
              key={label.text}
              className="map-label"
              x={label.x}
              y={label.y}
              transform={
                label.rotate
                  ? `rotate(${label.rotate} ${label.x} ${label.y})`
                  : undefined
              }
            >
              {label.text}
            </text>
          ))}
        </svg>

        {compact
          ? null
          : frame.packets.map((packet) => (
              <span
                key={packet.key}
                className="absolute size-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{
                  left: packet.x,
                  top: packet.y,
                  background: PACKET_COLOR[packet.status],
                  boxShadow: `0 0 12px ${PACKET_COLOR[packet.status]}`,
                }}
              />
            ))}
        {compact
          ? null
          : frame.sparks.map((spark) => (
              <span
                key={spark.key}
                className="absolute size-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{
                  left: spark.x,
                  top: spark.y,
                  background: "var(--map-live)",
                  boxShadow: "0 0 12px var(--map-live)",
                }}
              />
            ))}

        {compact
          ? null
          : frame.rows.map((row, index) => {
              const live = row.live > 0
              return (
                <div
                  key={row.id}
                  className="absolute flex flex-col justify-center gap-0.5 rounded-lg border bg-card px-3 py-2 transition-[border-color,box-shadow] duration-300"
                  style={{
                    ...place(modelRow(index)),
                    ...glow(live ? "live" : "idle"),
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className="size-[7px] shrink-0 rounded-full"
                        style={{
                          background: live
                            ? "var(--map-live)"
                            : "var(--map-idle)",
                        }}
                      />
                      <span className="truncate text-sm font-semibold">
                        {row.title}
                      </span>
                    </span>
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {row.provider}
                    </span>
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {row.roles}
                  </div>
                  <div className="truncate font-mono text-[11px] text-muted-foreground tabular-nums">
                    {row.stat}
                  </div>
                </div>
              )
            })}
        {compact
          ? null
          : (Object.keys(STORES) as StoreId[]).map((store) => (
              <div
                key={store}
                className="absolute flex flex-col justify-center gap-0.5 rounded-lg border bg-card px-3 py-2 transition-[border-color,box-shadow] duration-300"
                style={{
                  ...place(STORES[store]),
                  ...glow(frame.stores[store].live ? "live" : "idle"),
                }}
              >
                <span className="flex items-center gap-2">
                  <span
                    className="size-[7px] rounded-full"
                    style={{
                      background: frame.stores[store].live
                        ? "var(--map-live)"
                        : "var(--map-idle)",
                    }}
                  />
                  <span className="text-sm font-semibold">
                    {STORE_TEXT[store].title}
                  </span>
                </span>
                <div className="truncate text-xs text-muted-foreground">
                  {STORE_TEXT[store].sub}
                </div>
                <div className="truncate font-mono text-[11px] text-muted-foreground tabular-nums">
                  {frame.stores[store].stat}
                </div>
              </div>
            ))}
        <NodeCard
          id="customers"
          view={nodes.customers}
          title="Customers"
          tag="simulated"
        />
        <NodeCard
          id="store"
          view={nodes.store}
          title="Store"
          tag="hourly check"
        />
        <div
          className="absolute flex items-center justify-between rounded-lg border bg-card px-3.5 transition-[border-color,box-shadow] duration-300"
          style={{ ...place(NODES.screen), ...glow(nodes.screen.tone) }}
        >
          <span className="flex items-center gap-2.5">
            <StatusDot view={nodes.screen} />
            <span className="text-sm font-semibold">Input check</span>
            <span className="text-xs text-muted-foreground">
              patterns, then a classifier
            </span>
          </span>
          <span className="font-mono text-[11px] tabular-nums">
            {nodes.screen.stat}
          </span>
        </div>
        <NodeCard
          id="dispatcher"
          view={nodes.dispatcher}
          title="Dispatcher"
          tag={model("dispatcher")}
          href="/agents/dispatcher"
        />
        <NodeCard
          id="support"
          view={nodes.support}
          title="Support"
          sub={agent("support")}
          href="/agents/support"
        />
        <NodeCard
          id="ops"
          view={nodes.ops}
          title="Ops analyst"
          sub={agent("ops")}
          href="/agents/ops"
        />
        <NodeCard
          id="insights"
          view={nodes.insights}
          title="Insights"
          sub={agent("insights")}
          href="/agents/insights"
        />
        <NodeCard
          id="you"
          view={nodes.you}
          title="You"
          tag="approvals, proposals"
          href="/approvals"
        />
        <NodeCard id="qa" view={nodes.qa} title="QA reviewer" href="/quality" />

        {frame.tags.map((tag) => (
          <span
            key={tag.key}
            className="absolute rounded-md border bg-background/90 px-1.5 py-0.5 font-mono text-[11px] whitespace-nowrap"
            style={{
              left: tag.x,
              top: tag.y,
              borderColor: PACKET_COLOR[tag.status],
            }}
          >
            {tag.text}
          </span>
        ))}
        {frame.dots.map((dot) => {
          const color = DOT_COLOR[dot.tone]
          const style: CSSProperties = {
            left: dot.x,
            top: dot.y,
            width: dot.size,
            height: dot.size,
            marginLeft: -dot.size / 2,
            marginTop: -dot.size / 2,
            background: color,
            opacity: dot.opacity,
            boxShadow: `0 0 12px ${color}`,
          }
          return dot.workItemId && onPick ? (
            <button
              key={dot.key}
              type="button"
              aria-label={`Open the run of ${dot.workItemId}`}
              onClick={() => onPick(dot.workItemId ?? "")}
              className={cn(
                "absolute cursor-pointer rounded-full",
                dot.waiting && "map-wait"
              )}
              style={style}
            />
          ) : (
            <span
              key={dot.key}
              className={cn("absolute rounded-full", dot.waiting && "map-wait")}
              style={style}
            />
          )
        })}

        <div
          className="absolute flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground"
          style={{
            left: compact ? COMPACT.x + 8 : 312,
            top: 740,
            width: compact ? COMPACT.width - 16 : 760,
          }}
        >
          {(
            [
              ["ticket", "ticket"],
              ["alert", "alert"],
              ["flag", "flag"],
              ["attack", "held or refused"],
              ["reply", "reply"],
            ] as const
          ).map(([tone, label]) => (
            <span key={tone} className="flex items-center gap-1.5">
              <span
                className="size-2.5 rounded-full"
                style={{ background: DOT_COLOR[tone] }}
              />
              {label}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span
              className="map-wait size-2.5 rounded-full"
              style={{ background: "var(--map-amber)" }}
            />
            waiting for you
          </span>
          {compact ? null : (
            <>
              <span className="flex items-center gap-1.5">
                <span
                  className="w-5 border-t-2 border-dashed"
                  style={{ borderColor: "var(--map-live)" }}
                />
                model call
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  className="w-5 border-t-2 border-dotted"
                  style={{ borderColor: "var(--map-live)" }}
                />
                tool call
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

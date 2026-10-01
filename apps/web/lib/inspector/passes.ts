import type { AhqEvent, MessageView, ThreadView } from "@/lib/api/types"
import { flag, list, num, record, text } from "@/lib/scene/payload"

export const AGENT_ORDER = ["support", "ops", "insights"] as const
const TOKENS_PER_CHAR = 1 / 4

export type Approval = {
  approvalId: string | null
  requestedAt: number
  decidedAt: number | null
  verdict: string | null
  reason: string
}

export type CallStep = {
  id: string
  tool: string
  args: Record<string, unknown>
  at: number
  seconds: number
  verdict: "allowed" | "approved" | "refused" | "pending"
  reason: string | null
  cached: boolean
  ok: boolean
  error: string | null
  summary: string
  output: string | null
  approval: Approval | null
}

export type Composition = {
  system: number
  conversation: number
  tools: number
}

export type Answer = {
  status: string | null
  reply: string | null
  citations: string[]
  summary: string | null
  fields: Record<string, unknown>
}

export type Pass = {
  key: string
  agent: string
  n: number
  at: number
  seconds: number
  cost: number
  model: string
  input: number
  cached: number
  output: number
  reasoning: string | null
  text: string
  repair: boolean
  calls: CallStep[]
  answer: Answer | null
  context: MessageView[]
  composition: Composition
}

export type Entry =
  | { kind: "pass"; pass: Pass }
  | { kind: "customer"; at: number; text: string; opening: boolean }
  | { kind: "handoff"; at: number; from: string; to: string; brief: string }

export type Bar = {
  start: number
  end: number
  tone: "triage" | "agent" | "tool" | "refused" | "wait"
  pass?: string
}
export type Lane = {
  key: string
  label: string
  bars: Bar[]
  marks: { at: number; label: string }[]
}

export type Screening = {
  blocked: boolean
  threat: string
  reason: string
  by: string
  seconds: number | null
}
export type Route = {
  route: string
  priority: string | null
  reason: string
  seconds: number | null
}

export type Inspection = {
  origin: number
  duration: number
  agents: string[]
  passes: Pass[]
  entries: Entry[]
  lanes: Lane[]
  screening: Screening | null
  route: Route | null
  heldReplies: number
  citations: { cited: string[]; problems: string[] }
}

function time(event: AhqEvent): number {
  return Date.parse(event.recorded_at ?? event.occurred_at)
}

function tokens(message: MessageView): number {
  return Math.round(message.text.length * TOKENS_PER_CHAR)
}

export const REPLY_TOOL = "reply"

export function answerOf(textValue: string): Answer | null {
  try {
    const fields = JSON.parse(textValue) as unknown
    if (
      fields === null ||
      typeof fields !== "object" ||
      Array.isArray(fields)
    ) {
      return null
    }
    const data = fields as Record<string, unknown>
    return {
      status: typeof data.status === "string" ? data.status : null,
      reply: typeof data.reply === "string" ? data.reply : null,
      citations: Array.isArray(data.citations)
        ? data.citations.filter((c): c is string => typeof c === "string")
        : [],
      summary: typeof data.summary === "string" ? data.summary : null,
      fields: data,
    }
  } catch {
    return null
  }
}

function summarize(tool: string, payload: AhqEvent["payload"]): string {
  const result = record(payload, "result")
  if (!result) {
    return ""
  }
  const passages = list(result, "passages")
  if (passages.length > 0) {
    return `${passages.length} passages: ${passages.slice(0, 3).join(", ")}`
  }
  if (Object.keys(result).length === 0) {
    return ""
  }
  const parts = Object.entries(result).map(([key, value]) =>
    key === "text"
      ? String(value)
      : `${key.replaceAll("_", " ")} ${typeof value === "object" ? JSON.stringify(value) : String(value)}`
  )
  return parts.join(", ") || tool
}

export function inspect(
  events: readonly AhqEvent[],
  thread: ThreadView | null | undefined,
  now: number | null = null
): Inspection {
  const ordered = [...events].sort((a, b) => a.id - b.id)
  const origin = ordered.length > 0 ? Math.min(...ordered.map(time)) : 0
  const at = (event: AhqEvent) => time(event) - origin

  const channels = thread?.channels ?? {}
  const modelMessages = (agent: string) =>
    (channels[agent] ?? []).filter((m) => m.kind === "model")
  const toolOutput = (agent: string, callId: string) =>
    (channels[agent] ?? []).find(
      (m) => m.kind === "tool" && m.tool_call_id === callId
    )?.text ?? null

  const passes: Pass[] = []
  const entries: Entry[] = []
  const approvals: Approval[] = []
  const approvalAction = new Map<Approval, string>()
  let screening: Screening | null = null
  let route: Route | null = null
  let routing: number | null = null
  let heldReplies = 0
  const cited: string[] = []
  const problems: string[] = []
  const lanes = new Map<string, Lane>()
  const lane = (key: string, label: string) => {
    const found = lanes.get(key)
    if (found) {
      return found
    }
    const created: Lane = { key, label, bars: [], marks: [] }
    lanes.set(key, created)
    return created
  }

  const opening = (channels.support ?? []).find((m) => m.kind === "customer")
  if (opening) {
    entries.push({ kind: "customer", at: 0, text: opening.text, opening: true })
  }

  for (const event of ordered) {
    const payload = event.payload
    const actor = event.actor ?? ""
    const when = at(event)
    switch (event.kind) {
      case "model.called": {
        const seconds = num(payload, "seconds") ?? 0
        const start = when - seconds * 1000
        if (actor === "guard") {
          lane("screen", "Input check").bars.push({
            start,
            end: when,
            tone: "triage",
          })
          const verdict = record(payload, "screening")
          if (verdict && !screening) {
            screening = {
              blocked: verdict.blocked === true,
              threat: String(verdict.threat ?? "none"),
              reason: String(verdict.reason ?? ""),
              by: String(verdict.by ?? "model"),
              seconds,
            }
          }
          break
        }
        if (actor === "dispatcher") {
          lane("dispatcher", "Dispatcher").bars.push({
            start,
            end: when,
            tone: "triage",
          })
          routing = seconds
          break
        }
        if (!(AGENT_ORDER as readonly string[]).includes(actor)) {
          break
        }
        const n =
          num(payload, "pass") ??
          passes.filter((p) => p.agent === actor).length + 1
        const repair = flag(payload, "repair") === true
        const messageId = text(payload, "message_id")
        const messages = modelMessages(actor)
        const message = repair
          ? undefined
          : (messages.find((m) => m.id === messageId) ??
            messages[
              passes.filter((p) => p.agent === actor && !p.repair).length
            ])
        const channel = channels[actor] ?? []
        const index = message ? channel.indexOf(message) : channel.length
        const context = channel.slice(0, Math.max(0, index))
        const usage = record(payload, "usage") ?? {}
        const fresh = Number(usage.input_tokens ?? 0)
        const cachedTokens = Number(usage.cache_read_tokens ?? 0)
        const written = Number(usage.cache_write_tokens ?? 0)
        const input = fresh + cachedTokens + written
        const conversation = context
          .filter((m) => m.kind !== "tool")
          .reduce((sum, m) => sum + tokens(m), 0)
        const toolTokens = context
          .filter((m) => m.kind === "tool")
          .reduce((sum, m) => sum + tokens(m), 0)
        const key = `${actor}:${n}${repair ? ":repair" : ""}`
        const pass: Pass = {
          key,
          agent: actor,
          n,
          at: start,
          seconds,
          cost: num(payload, "cost_usd") ?? 0,
          model: text(payload, "model") ?? "",
          input,
          cached: cachedTokens,
          output: Number(usage.output_tokens ?? 0),
          reasoning: message?.reasoning ?? null,
          text: message?.text ?? "",
          repair,
          calls: [],
          answer: null,
          context,
          composition: {
            system: Math.max(0, input - conversation - toolTokens),
            conversation: Math.min(conversation, input),
            tools: Math.min(toolTokens, Math.max(0, input - conversation)),
          },
        }
        const asked = list(payload, "tools")
        const replied = (message?.tool_calls ?? []).find(
          (call) => call.name === REPLY_TOOL
        )
        if (replied) {
          pass.answer = answerOf(JSON.stringify(replied.arguments))
        } else if (asked.length === 0 && message) {
          pass.answer = answerOf(message.text)
        }
        for (const call of asked) {
          const request =
            typeof call === "object" && call !== null
              ? (call as Record<string, unknown>)
              : {}
          const callId = String(request.id ?? "")
          const tool = String(request.name ?? "tool")
          if (tool === REPLY_TOOL) {
            continue
          }
          const view = (message?.tool_calls ?? []).find((c) => c.id === callId)
          pass.calls.push({
            id: callId,
            tool,
            args:
              (view?.arguments as Record<string, unknown> | undefined) ?? {},
            at: when,
            seconds: 0,
            verdict: "pending",
            reason: null,
            cached: false,
            ok: true,
            error: null,
            summary: "",
            output: null,
            approval: null,
          })
        }
        passes.push(pass)
        entries.push({ kind: "pass", pass })
        lane(`${actor}:model`, `${name(actor)}: model`).bars.push({
          start,
          end: when,
          tone: "agent",
          pass: key,
        })
        break
      }
      case "tool.called": {
        const pass = [...passes].reverse().find((p) => p.agent === actor)
        if (!pass) {
          break
        }
        const seconds = num(payload, "seconds") ?? 0
        const start = when - seconds * 1000
        const verdict = (text(payload, "verdict") ??
          "allowed") as CallStep["verdict"]
        const callId =
          text(payload, "call_id") ?? `${pass.key}:${pass.calls.length}`
        const tool = text(payload, "tool") ?? "tool"
        const approvalId = text(payload, "approval_id")
        const index = pass.calls.findIndex((c) => c.id === callId)
        const placeholder = index >= 0 ? pass.calls[index] : null
        const approval =
          approvals.find(
            (a) => approvalId !== null && a.approvalId === approvalId
          ) ??
          placeholder?.approval ??
          null
        const step: CallStep = {
          id: callId,
          tool,
          args: record(payload, "arguments") ?? placeholder?.args ?? {},
          at: start,
          seconds,
          verdict,
          reason: text(payload, "reason"),
          cached: flag(payload, "cached") === true,
          ok: flag(payload, "ok") !== false,
          error: text(payload, "error"),
          summary: summarize(tool, payload),
          output: toolOutput(actor, callId),
          approval,
        }
        if (index >= 0) {
          pass.calls[index] = step
        } else {
          pass.calls.push(step)
        }
        lane(`${actor}:tools`, `${name(actor)}: tools`).bars.push({
          start,
          end: Math.max(when, start + 1),
          tone: verdict === "refused" ? "refused" : "tool",
          pass: pass.key,
        })
        break
      }
      case "approval.requested": {
        const approval: Approval = {
          approvalId: text(payload, "approval_id"),
          requestedAt: when,
          decidedAt: null,
          verdict: null,
          reason: text(payload, "reason") ?? "",
        }
        approvals.push(approval)
        const action = text(payload, "action") ?? ""
        approvalAction.set(approval, action)
        const waiting = [...passes]
          .reverse()
          .flatMap((p) => p.calls)
          .find(
            (c) =>
              c.tool === action &&
              c.verdict === "pending" &&
              c.approval === null
          )
        if (waiting) {
          waiting.approval = approval
        }
        break
      }
      case "approval.decided": {
        const approvalId = text(payload, "approval_id")
        const approval =
          approvals.find((a) => a.approvalId === approvalId) ??
          approvals.find((a) => a.decidedAt === null)
        if (approval) {
          approval.decidedAt = when
          approval.verdict = text(payload, "verdict")
          lane("you", "You").bars.push({
            start: approval.requestedAt,
            end: when,
            tone: "wait",
          })
        }
        break
      }
      case "work.routed":
        route = {
          route: text(payload, "route") ?? "",
          priority: text(payload, "priority"),
          reason: text(payload, "reason") ?? "",
          seconds: routing,
        }
        break
      case "guardrail.blocked":
        if (text(payload, "stage") === "output") {
          heldReplies += 1
        } else if (!screening) {
          screening = {
            blocked: true,
            threat: text(payload, "threat") ?? "unknown",
            reason: text(payload, "reason") ?? "",
            by: text(payload, "by") ?? "pattern",
            seconds: null,
          }
        }
        break
      case "ticket.message":
        if (actor === "customer") {
          entries.push({
            kind: "customer",
            at: when,
            text: text(payload, "body") ?? "",
            opening: false,
          })
          lane("customer", "Customer").marks.push({ at: when, label: "writes" })
        }
        break
      case "ticket.replied":
        lane("customer", "Customer").marks.push({
          at: when,
          label: "gets a reply",
        })
        cited.push(
          ...list(payload, "citations").filter(
            (c): c is string => typeof c === "string"
          )
        )
        for (const problem of list(payload, "citation_problems")) {
          const id =
            typeof problem === "object" && problem !== null
              ? (problem as Record<string, unknown>).passage_id
              : null
          if (typeof id === "string") {
            problems.push(id)
          }
        }
        break
      case "agent.handoff":
        entries.push({
          kind: "handoff",
          at: when,
          from: text(payload, "from") ?? actor,
          to: text(payload, "to") ?? "",
          brief: text(payload, "brief") ?? "",
        })
        break
      default:
        break
    }
  }

  for (const approval of approvals) {
    if (approval.decidedAt === null) {
      const end =
        now !== null
          ? Math.max(approval.requestedAt + 1, now - origin)
          : approval.requestedAt + 1
      lane("you", "You").bars.push({
        start: approval.requestedAt,
        end,
        tone: "wait",
      })
    }
  }

  const agents = AGENT_ORDER.filter((agent) =>
    passes.some((p) => p.agent === agent)
  )
  const orderedLanes = [
    lanes.get("screen"),
    lanes.get("dispatcher"),
    ...agents.flatMap((agent) => [
      lanes.get(`${agent}:model`),
      lanes.get(`${agent}:tools`),
    ]),
    lanes.get("you"),
    lanes.get("customer"),
  ].filter((l): l is Lane => l !== undefined)
  const ends = orderedLanes.flatMap((l) => [
    ...l.bars.map((b) => b.end),
    ...l.marks.map((m) => m.at),
  ])
  return {
    origin,
    duration: Math.max(1, ...ends),
    agents,
    passes,
    entries: entries.sort((a, b) => entryAt(a) - entryAt(b)),
    lanes: orderedLanes,
    screening,
    route,
    heldReplies,
    citations: { cited: [...new Set(cited)], problems: [...new Set(problems)] },
  }
}

function entryAt(entry: Entry): number {
  return entry.kind === "pass" ? entry.pass.at : entry.at
}

const NAMES: Record<string, string> = {
  support: "Support",
  ops: "Ops",
  insights: "Insights",
  dispatcher: "Dispatcher",
}

export function name(agent: string): string {
  return NAMES[agent] ?? agent
}

export type Axis = {
  toX: (t: number) => number
  width: number
  folds: { x: number; ms: number }[]
}

export function foldedAxis(
  lanes: Lane[],
  width: number,
  gapMs = 8000,
  foldPx = 40
): Axis {
  const spans = lanes
    .flatMap((l) => [
      ...l.bars
        .filter((b) => b.tone !== "wait")
        .map((b) => [b.start, b.end] as const),
      ...l.marks.map((m) => [m.at, m.at] as const),
    ])
    .sort((a, b) => a[0] - b[0])
  const gaps: [number, number][] = []
  let reach = spans.length > 0 ? spans[0][1] : 0
  for (const [start, end] of spans.slice(1)) {
    if (start - reach > gapMs) {
      gaps.push([reach, start])
    }
    reach = Math.max(reach, end)
  }
  const first = spans.length > 0 ? Math.min(0, spans[0][0]) : 0
  const folded = gaps.reduce((sum, [a, b]) => sum + (b - a), 0)
  const kept = Math.max(1, reach - first - folded)
  const scale = (width - gaps.length * foldPx) / kept
  const toX = (t: number) => {
    let x = (t - first) * scale
    for (const [a, b] of gaps) {
      if (t >= b) {
        x += foldPx - (b - a) * scale
      } else if (t > a) {
        x += ((t - a) / (b - a)) * foldPx - (t - a) * scale
      }
    }
    return Math.max(0, Math.min(width, x))
  }
  return { toX, width, folds: gaps.map(([a, b]) => ({ x: toX(a), ms: b - a })) }
}

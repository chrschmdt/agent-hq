import type {
  AgentDetail,
  AgentScorecards,
  AgentSummary,
  AgentVersion,
  AhqEvent,
  Approval,
  GuardrailSummary,
  Incident,
  KbDraft,
  KpiPoint,
  PathStep,
  ProposalRecord,
  Recording,
  RecordedAgent,
  RecordedRun,
  RecordedWork,
  ReviewRecord,
  RunView,
  SimRun,
  Status,
  TeamValue,
  ThreadView,
  Ticket,
  WorkItem,
  WorkStatus,
} from "@/lib/api/types"
import { simulatedAt } from "@/lib/scene/frame"
import { buildTimeline, type Timeline, wallTimes } from "@/lib/scene/timeline"

export const FEED_SIZE = 200
const RECENT_EVENTS = 50
const RECENT_WORK = 20
const ACTIVE: readonly WorkStatus[] = ["new", "running"]
const ACTIVITY = new Set([
  "model.called",
  "tool.called",
  "agent.handoff",
  "work.routed",
])
const SIM_STATUS: Record<string, SimRun["status"]> = {
  "sim.started": "running",
  "sim.resumed": "running",
  "sim.paused": "paused",
  "sim.finished": "finished",
  "sim.stopped": "stopped",
}

export type Prepared = {
  recording: Recording
  timeline: Timeline
  events: AhqEvent[]
  offsets: number[]
  last: number
  position: Map<number, number>
  work: Map<string, RecordedWork>
  runs: Map<string, RecordedRun>
  agents: Map<string, RecordedAgent>
}

export function prepare(recording: Recording): Prepared {
  const events = [...recording.events].sort((a, b) => a.id - b.id)
  const timeline = buildTimeline(events, recording.lineup)
  let high = 0
  const offsets = wallTimes(events).map((time) => {
    high = Math.max(high, time - timeline.origin)
    return high
  })
  return {
    recording,
    timeline,
    events,
    offsets,
    last: events.at(-1)?.id ?? 0,
    position: new Map(events.map((event, index) => [event.id, index])),
    work: new Map(recording.work.map((work) => [work.item.id, work])),
    runs: new Map(Object.entries(recording.runs)),
    agents: new Map(
      recording.agents.map((agent) => [agent.detail.name, agent])
    ),
  }
}

export function cursorAt(prepared: Prepared, t: number): number {
  const { offsets, events } = prepared
  let low = 0
  let high = offsets.length - 1
  let found = -1
  while (low <= high) {
    const middle = (low + high) >> 1
    if (offsets[middle] <= t) {
      found = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }
  return found < 0 ? 0 : events[found].id
}

export function momentOf(prepared: Prepared, cursor: number): number {
  const { events, offsets, timeline } = prepared
  let low = 0
  let high = events.length - 1
  let found = -1
  while (low <= high) {
    const middle = (low + high) >> 1
    if (events[middle].id <= cursor) {
      found = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }
  return timeline.origin + (found < 0 ? 0 : offsets[found])
}

export function storeTimeOf(prepared: Prepared, event: AhqEvent): string {
  const index = prepared.position.get(event.id)
  const simulated =
    index === undefined
      ? null
      : simulatedAt(prepared.timeline, prepared.offsets[index])
  return simulated === null
    ? event.occurred_at
    : new Date(simulated).toISOString()
}

type Settling<T> = {
  at: number
  settled_at?: number | null
  pending: T
  record: T
}

function settled<T>(entry: Settling<T>, cursor: number): T {
  return entry.settled_at != null && entry.settled_at <= cursor
    ? entry.record
    : entry.pending
}

function newest<T>(list: T[], time: (value: T) => string): T[] {
  return list.sort((a, b) => Date.parse(time(b)) - Date.parse(time(a)))
}

export function itemAt(work: RecordedWork, cursor: number): WorkItem {
  const change =
    work.changes.findLast((candidate) => candidate.at <= cursor) ??
    work.changes[0]
  return {
    ...work.item,
    status: change.status,
    owner: change.owner ?? null,
    updated_at: change.updated_at,
  }
}

export function workAt(prepared: Prepared, cursor: number): WorkItem[] {
  return newest(
    prepared.recording.work
      .filter((work) => work.at <= cursor)
      .map((work) => itemAt(work, cursor)),
    (item) => item.updated_at
  )
}

export function statusAt(prepared: Prepared, cursor: number): Status {
  const items = workAt(prepared, cursor)
  const sim = simStatusAt(prepared, cursor)
  const activeWork = items.filter((item) => ACTIVE.includes(item.status)).length
  const pending = approvalsAt(prepared, cursor).length
  return {
    active_work: activeWork,
    pending_approvals: pending,
    simulating: sim === "running",
    last_event_id: cursor,
    active: activeWork > 0 || pending > 0 || sim === "running",
  }
}

function simStatusAt(prepared: Prepared, cursor: number): SimRun["status"] {
  let status: SimRun["status"] = "running"
  for (const event of prepared.events) {
    if (event.id > cursor) {
      break
    }
    status = SIM_STATUS[event.kind] ?? status
  }
  return status
}

export function simAt(
  prepared: Prepared,
  cursor: number,
  simulated: number | null
): SimRun {
  const run = prepared.recording.sim_run
  const status = simStatusAt(prepared, cursor)
  const now =
    simulated !== null
      ? new Date(simulated).toISOString()
      : cursor >= prepared.last
        ? run.sim_now
        : run.started_at
  return { ...run, status, sim_now: now }
}

export function approvalsAt(prepared: Prepared, cursor: number): Approval[] {
  return prepared.recording.approvals
    .filter((entry) => entry.at <= cursor)
    .map((entry) => settled(entry, cursor))
    .filter((approval) => approval.status === "pending")
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
}

export function decidedAt(prepared: Prepared, cursor: number): Approval[] {
  return prepared.recording.approvals
    .filter((entry) => entry.settled_at != null && entry.settled_at <= cursor)
    .sort((a, b) => (b.settled_at ?? 0) - (a.settled_at ?? 0))
    .map((entry) => entry.record)
}

export function approvalAt(
  prepared: Prepared,
  cursor: number,
  id: string
): Approval | null {
  const entry = prepared.recording.approvals.find(
    (candidate) => candidate.record.id === id
  )
  return entry && entry.at <= cursor ? settled(entry, cursor) : null
}

export function incidentsAt(prepared: Prepared, cursor: number): Incident[] {
  return newest(
    prepared.recording.incidents
      .filter((entry) => entry.at <= cursor)
      .map((entry) => entry.record),
    (incident) => incident.created_at
  )
}

export function incidentAt(
  prepared: Prepared,
  cursor: number,
  id: string
): Incident | null {
  const entry = prepared.recording.incidents.find(
    (candidate) => candidate.record.incident_id === id
  )
  return entry && entry.at <= cursor ? entry.record : null
}

export function proposalsAt(
  prepared: Prepared,
  cursor: number
): ProposalRecord[] {
  return newest(
    prepared.recording.proposals
      .filter((entry) => entry.at <= cursor)
      .map((entry) => settled(entry, cursor)),
    (proposal) => proposal.created_at
  )
}

export function proposalAt(
  prepared: Prepared,
  cursor: number,
  id: string
): ProposalRecord | null {
  const entry = prepared.recording.proposals.find(
    (candidate) => candidate.record.proposal_id === id
  )
  return entry && entry.at <= cursor ? settled(entry, cursor) : null
}

export function draftAt(
  prepared: Prepared,
  cursor: number,
  id: string
): KbDraft | null {
  const entry = prepared.recording.drafts.find(
    (candidate) => candidate.record.draft_id === id
  )
  return entry && entry.at <= cursor ? settled(entry, cursor) : null
}

export function reviewsAt(prepared: Prepared, cursor: number): ReviewRecord[] {
  return newest(
    prepared.recording.reviews
      .filter((entry) => entry.at <= cursor)
      .map((entry) => entry.record),
    (review) => review.created_at
  )
}

const NOTHING_BLOCKED: GuardrailSummary = {
  inputs_blocked: 0,
  replies_held: 0,
  by_threat: {},
  recent: [],
}

export function guardrailsAt(
  prepared: Prepared,
  cursor: number
): GuardrailSummary {
  return (
    prepared.recording.guardrails.findLast((point) => point.at <= cursor)
      ?.summary ?? NOTHING_BLOCKED
  )
}

export function valueAt(prepared: Prepared, cursor: number): TeamValue | null {
  return (
    prepared.recording.value.findLast((point) => point.at <= cursor)?.value ??
    null
  )
}

export function kpisOf(prepared: Prepared, metric: string): KpiPoint[] {
  return prepared.recording.kpis[metric] ?? []
}

export function feedAt(
  prepared: Prepared,
  cursor: number,
  limit = FEED_SIZE
): AhqEvent[] {
  const shown: AhqEvent[] = []
  for (let index = prepared.events.length - 1; index >= 0; index--) {
    const event = prepared.events[index]
    if (event.id <= cursor) {
      shown.push(event)
      if (shown.length >= limit) {
        break
      }
    }
  }
  return shown
}

function workCounts(
  prepared: Prepared,
  cursor: number,
  name: string
): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const item of workAt(prepared, cursor)) {
    if (item.owner === name) {
      counts[item.status] = (counts[item.status] ?? 0) + 1
    }
  }
  return counts
}

export function agentsAt(prepared: Prepared, cursor: number): AgentSummary[] {
  return prepared.recording.agents.map(({ detail }) => ({
    ...detail,
    work: workCounts(prepared, cursor, detail.name),
  }))
}

export function agentAt(
  prepared: Prepared,
  cursor: number,
  name: string
): AgentDetail | null {
  const recorded = prepared.agents.get(name)
  if (!recorded) {
    return null
  }
  const recent = feedAt(prepared, cursor, prepared.events.length)
    .filter((event) => event.actor === name && ACTIVITY.has(event.kind))
    .slice(0, RECENT_EVENTS)
  return {
    ...recorded.detail,
    work: workCounts(prepared, cursor, name),
    recent_events: recent,
    recent_work: workAt(prepared, cursor)
      .filter((item) => item.owner === name)
      .slice(0, RECENT_WORK),
  }
}

export function versionsOf(prepared: Prepared, name: string): AgentVersion[] {
  return prepared.agents.get(name)?.versions ?? []
}

export function scorecardsOf(
  prepared: Prepared,
  name: string
): AgentScorecards | null {
  return prepared.agents.get(name)?.scorecards ?? null
}

function clip(
  step: PathStep,
  events: AhqEvent[],
  cursor: number
): PathStep | null {
  if (step.first_event_id > cursor) {
    return null
  }
  if (step.last_event_id <= cursor) {
    return step
  }
  const inside = events.filter(
    (event) => event.id >= step.first_event_id && event.id <= cursor
  )
  const cost = inside.reduce((total, event) => {
    const value = event.payload?.cost_usd
    return (
      total +
      (event.kind === "model.called" && typeof value === "number" ? value : 0)
    )
  }, 0)
  return {
    ...step,
    last_event_id: inside.at(-1)?.id ?? step.first_event_id,
    ended_at: inside.at(-1)?.occurred_at ?? step.started_at,
    model_calls: inside.filter((event) => event.kind === "model.called").length,
    tool_calls: inside.filter((event) => event.kind === "tool.called").length,
    cost_usd: cost,
    waited_for_approval:
      step.waited_for_approval &&
      inside.some((event) => event.kind === "approval.requested"),
  }
}

function ticketAt(
  ticket: Ticket | null | undefined,
  item: WorkItem,
  events: AhqEvent[]
): Ticket | null {
  if (!ticket) {
    return null
  }
  const said = events.filter(
    (event) =>
      event.kind === "ticket.message" ||
      event.kind === "ticket.replied" ||
      (event.kind === "ticket.closed" && event.actor === "customer")
  ).length
  const status: Ticket["status"] =
    item.status === "done"
      ? "resolved"
      : item.status === "escalated"
        ? "escalated"
        : item.status === "waiting_customer"
          ? "waiting_customer"
          : "open"
  return {
    ...ticket,
    status,
    messages: ticket.messages.slice(0, 1 + said),
  }
}

function threadAt(recorded: RecordedRun, cursor: number): ThreadView | null {
  const thread = recorded.thread
  if (!thread) {
    return null
  }
  const channels: ThreadView["channels"] = {}
  for (const [channel, messages] of Object.entries(thread.channels)) {
    const times = recorded.message_at[channel] ?? []
    channels[channel] = messages.filter(
      (_, index) => (times[index] ?? 0) <= cursor
    )
  }
  return { ...thread, channels }
}

export function runAt(
  prepared: Prepared,
  cursor: number,
  id: string
): { run: RunView; thread: ThreadView | null } | null {
  const recorded = prepared.runs.get(id)
  const work = prepared.work.get(id)
  if (!recorded || !work || work.at > cursor) {
    return null
  }
  const events = prepared.events.filter(
    (event) => event.work_item_id === id && event.id <= cursor
  )
  const allEvents = prepared.events.filter((event) => event.work_item_id === id)
  const path = recorded.path.flatMap((step) => {
    const shown = clip(step, allEvents, cursor)
    return shown ? [shown] : []
  })
  const sum = (field: "model_calls" | "tool_calls" | "cost_usd") =>
    path.reduce((total, step) => total + (step[field] ?? 0), 0)
  const item = itemAt(work, cursor)
  const incident = prepared.recording.incidents.find(
    (entry) => entry.record.work_item_id === id && entry.at <= cursor
  )
  const approvals = recorded.approvals.flatMap((summary) => {
    const entry = prepared.recording.approvals.find(
      (candidate) => candidate.record.id === summary.approval_id
    )
    if (!entry || entry.at > cursor) {
      return []
    }
    const decided = entry.settled_at != null && entry.settled_at <= cursor
    return [{ ...summary, verdict: decided ? summary.verdict : null }]
  })
  return {
    run: {
      item,
      events,
      path,
      model_calls: sum("model_calls"),
      tool_calls: sum("tool_calls"),
      cost_usd: sum("cost_usd"),
      approvals,
      ticket: ticketAt(recorded.ticket, item, events),
      incident: incident?.record ?? null,
      proposals: prepared.recording.proposals
        .filter(
          (entry) => entry.record.work_item_id === id && entry.at <= cursor
        )
        .map((entry) => settled(entry, cursor)),
      traced: false,
      agent_runs: recorded.agent_runs,
      reviews: prepared.recording.reviews
        .filter(
          (entry) => entry.record.work_item_id === id && entry.at <= cursor
        )
        .map((entry) => entry.record),
    },
    thread: threadAt(recorded, cursor),
  }
}

export function eventsAt(
  prepared: Prepared,
  cursor: number,
  kinds: readonly string[]
): AhqEvent[] {
  return feedAt(prepared, cursor, prepared.events.length).filter((event) =>
    kinds.includes(event.kind)
  )
}

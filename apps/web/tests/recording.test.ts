import { describe, expect, it } from "vitest"

import type {
  AhqEvent,
  Approval,
  Recording,
  TeamValue,
  WorkItem,
} from "@/lib/api/types"
import {
  approvalAt,
  approvalsAt,
  cursorAt,
  decidedAt,
  feedAt,
  momentOf,
  prepare,
  runAt,
  statusAt,
  valueAt,
  workAt,
} from "@/lib/recording/derive"

const T0 = Date.parse("2026-09-28T15:00:00Z")
const at = (seconds: number) => new Date(T0 + seconds * 1000).toISOString()

function event(
  id: number,
  kind: AhqEvent["kind"],
  seconds: number,
  actor: string,
  payload: Record<string, unknown> = {},
  work: string | null = "wi_1"
): AhqEvent {
  return {
    id,
    kind,
    occurred_at: at(seconds),
    recorded_at: at(seconds),
    actor,
    work_item_id: work,
    payload,
  }
}

const EVENTS: AhqEvent[] = [
  event(1, "sim.started", 0, "simulator", { run_id: "sim_1" }, null),
  event(2, "work.created", 1, "simulator", { kind: "ticket" }),
  event(3, "work.started", 2, "runtime", { action: "start" }),
  event(4, "model.called", 4, "support", {
    pass: 1,
    message_id: "m1",
    seconds: 1.5,
    cost_usd: 0.01,
  }),
  event(5, "approval.requested", 5, "runtime", { approval_id: "apv_1" }),
  event(6, "work.waiting_approval", 5, "runtime"),
  event(7, "approval.decided", 20, "operator", {
    approval_id: "apv_1",
    verdict: "approve",
  }),
  event(8, "work.started", 21, "runtime", { action: "resume" }),
  event(9, "model.called", 23, "support", {
    pass: 2,
    message_id: "m2",
    seconds: 1,
    cost_usd: 0.01,
  }),
  event(10, "work.completed", 24, "runtime", { outcome: "resolved" }),
  event(11, "sim.finished", 30, "simulator", { run_id: "sim_1" }, null),
]

const ITEM: WorkItem = {
  id: "wi_1",
  kind: "ticket",
  status: "done",
  thread_id: "wi_1",
  input: {},
  owner: "support",
  attempts: 1,
  last_error: null,
  created_at: at(1),
  updated_at: at(24),
}

const DECIDED: Approval = {
  id: "apv_1",
  work_item_id: "wi_1",
  interrupt_id: "i1",
  status: "approved",
  request: {
    action: "return_delivered_order_items",
    arguments: {},
    reason: "Refund over the limit",
    cost_usd: 140,
    evidence: [],
  },
  decision: { verdict: "approve", arguments: null, note: null },
  decided_by: "operator",
  created_at: at(5),
  decided_at: at(20),
}

function value(resolved: number): TeamValue {
  return { tickets: 1, resolved } as TeamValue
}

const RECORDING = {
  version: 2,
  id: "rec_1",
  title: "A day",
  recorded_at: at(40),
  profile: "mock",
  lineup: null,
  sim_run: {
    run_id: "sim_1",
    scenario: "normal-day",
    seed: 7,
    status: "finished",
    started_at: "2026-06-15T08:00:00-04:00",
    ends_at: "2026-06-16T08:00:00-04:00",
    sim_now: "2026-06-16T08:00:00-04:00",
    tick_no: 288,
    tick_minutes: 5,
    tick_seconds: 2,
    agent_tickets: 1,
    alerts_to_agents: false,
    created_at: at(0),
    updated_at: at(30),
  },
  events: EVENTS,
  work: [
    {
      at: 2,
      item: ITEM,
      changes: [
        { at: 2, status: "new", owner: null, updated_at: at(1) },
        { at: 3, status: "running", owner: "support", updated_at: at(2) },
        {
          at: 6,
          status: "waiting_approval",
          owner: "support",
          updated_at: at(5),
        },
        { at: 8, status: "running", owner: "support", updated_at: at(21) },
        { at: 10, status: "done", owner: "support", updated_at: at(24) },
      ],
    },
  ],
  approvals: [
    {
      at: 5,
      settled_at: 7,
      pending: {
        ...DECIDED,
        status: "pending",
        decision: null,
        decided_by: null,
        decided_at: null,
      },
      record: DECIDED,
    },
  ],
  incidents: [],
  proposals: [],
  drafts: [],
  reviews: [],
  runs: {
    wi_1: {
      item: ITEM,
      path: [
        {
          node: "support",
          started_at: at(2),
          ended_at: at(24),
          first_event_id: 3,
          last_event_id: 10,
          model_calls: 2,
          tool_calls: 0,
          cost_usd: 0.02,
          waited_for_approval: true,
        },
      ],
      approvals: [
        {
          approval_id: "apv_1",
          action: "return_delivered_order_items",
          reason: "Refund over the limit",
          verdict: "approve",
        },
      ],
      ticket: null,
      incident: null,
      proposals: [],
      agent_runs: [],
      reviews: [],
      thread: {
        channels: {
          support: [
            { id: "h1", kind: "customer", text: "Refund me", tool_calls: [] },
            { id: "m1", kind: "model", text: "", tool_calls: [] },
            { id: "m2", kind: "model", text: "Done", tool_calls: [] },
          ],
        },
        route: null,
        screening: null,
        outputs: {},
        retrieved: [],
        versions: {},
        verified_customer_id: null,
      },
      message_at: { support: [4, 4, 9] },
    },
  },
  value: [
    { at: 2, value: value(0) },
    { at: 10, value: value(1) },
  ],
  guardrails: [],
  kpis: {},
  agents: [],
} as unknown as Recording

describe("a recorded day at a moment", () => {
  const prepared = prepare(RECORDING)

  it("finds the last event that had happened by a time", () => {
    expect(cursorAt(prepared, -1)).toBe(0)
    expect(cursorAt(prepared, 0)).toBe(1)
    expect(cursorAt(prepared, 5_000)).toBe(6)
    expect(cursorAt(prepared, 19_999)).toBe(6)
    expect(cursorAt(prepared, prepared.timeline.duration)).toBe(11)
    expect(momentOf(prepared, 6)).toBe(T0 + 5_000)
  })

  it("shows each work item as it stood", () => {
    expect(workAt(prepared, 1)).toEqual([])
    expect(workAt(prepared, 2)[0].status).toBe("new")
    expect(workAt(prepared, 6)[0]).toMatchObject({
      status: "waiting_approval",
      owner: "support",
      updated_at: at(5),
    })
    expect(workAt(prepared, 11)[0].status).toBe("done")
  })

  it("keeps an approval waiting until it was decided", () => {
    expect(approvalsAt(prepared, 4)).toEqual([])
    expect(approvalsAt(prepared, 6).map((a) => a.status)).toEqual(["pending"])
    expect(statusAt(prepared, 6)).toMatchObject({
      active_work: 0,
      pending_approvals: 1,
      simulating: true,
    })
    expect(approvalAt(prepared, 6, "apv_1")?.decision).toBeNull()
    expect(approvalsAt(prepared, 7)).toEqual([])
    expect(decidedAt(prepared, 7).map((a) => a.status)).toEqual(["approved"])
    expect(statusAt(prepared, 11)).toMatchObject({
      active_work: 0,
      pending_approvals: 0,
      simulating: false,
    })
  })

  it("opens a run as far as it had gone", () => {
    expect(runAt(prepared, 1, "wi_1")).toBeNull()
    const early = runAt(prepared, 5, "wi_1")
    expect(early?.run.events.map((e) => e.id)).toEqual([2, 3, 4, 5])
    expect(early?.run.path[0]).toMatchObject({
      last_event_id: 5,
      model_calls: 1,
      cost_usd: 0.01,
    })
    expect(early?.run.approvals[0].verdict).toBeNull()
    expect(
      early?.thread?.channels.support.map((message) => message.id)
    ).toEqual(["h1", "m1"])
    const done = runAt(prepared, 11, "wi_1")
    expect(done?.run.item.status).toBe("done")
    expect(done?.run.model_calls).toBe(2)
    expect(done?.run.approvals[0].verdict).toBe("approve")
    expect(done?.thread?.channels.support).toHaveLength(3)
  })

  it("gives the feed and the value panel as they stood", () => {
    expect(feedAt(prepared, 3).map((e) => e.id)).toEqual([3, 2, 1])
    expect(valueAt(prepared, 1)).toBeNull()
    expect(valueAt(prepared, 9)?.resolved).toBe(0)
    expect(valueAt(prepared, 10)?.resolved).toBe(1)
  })
})

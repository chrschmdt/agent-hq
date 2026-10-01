import { describe, expect, it } from "vitest"

import type { AhqEvent, ProposalRecord, ThreadView } from "@/lib/api/types"
import { incidentChain } from "@/lib/inspector/chain"
import {
  answerOf,
  foldedAxis,
  inspect,
  REPLY_TOOL,
} from "@/lib/inspector/passes"

const T0 = Date.parse("2026-09-28T15:00:00Z")
let nextId = 1

function event(
  kind: AhqEvent["kind"],
  seconds: number,
  actor: string,
  payload: Record<string, unknown> = {},
  work = "wi_1"
): AhqEvent {
  const at = new Date(T0 + seconds * 1000).toISOString()
  return {
    id: nextId++,
    kind,
    occurred_at: at,
    recorded_at: at,
    actor,
    work_item_id: work,
    payload,
  }
}

const usage = {
  input_tokens: 400,
  cache_read_tokens: 5000,
  cache_write_tokens: 0,
  output_tokens: 120,
}

function ticketRun(): AhqEvent[] {
  nextId = 1
  return [
    event("work.created", 0, "simulator", { kind: "ticket" }),
    event("model.called", 1, "guard", {
      seconds: 0.6,
      screening: {
        blocked: false,
        threat: "none",
        reason: "An ordinary request.",
        by: "model",
      },
    }),
    event("model.called", 2, "dispatcher", { seconds: 0.8 }),
    event("work.routed", 2.1, "dispatcher", {
      route: "support",
      priority: "normal",
      reason: "An order request.",
    }),
    event("model.called", 4, "support", {
      seconds: 1.5,
      pass: 1,
      message_id: "m1",
      model: "claude-sonnet-5",
      cost_usd: 0.004,
      usage,
      tools: [{ id: "c1", name: "find_user_id_by_email" }],
    }),
    event("tool.called", 4.2, "support", {
      tool: "find_user_id_by_email",
      call_id: "c1",
      seconds: 0.12,
      verdict: "allowed",
      ok: true,
      cached: false,
      result: { text: "ada_1" },
      arguments: { email: "ada@example.com" },
    }),
    event("model.called", 6, "support", {
      seconds: 1.2,
      pass: 2,
      message_id: "m2",
      model: "claude-sonnet-5",
      usage,
      tools: [{ id: "c2", name: "return_delivered_order_items" }],
    }),
    event("approval.requested", 6.2, "runtime", {
      approval_id: "apv_1",
      action: "return_delivered_order_items",
      reason: "Refund $142.18 is over the $100 limit",
    }),
    event("approval.decided", 40, "operator", {
      approval_id: "apv_1",
      verdict: "approve",
    }),
    event("tool.called", 41, "support", {
      tool: "return_delivered_order_items",
      call_id: "c2",
      seconds: 0.3,
      verdict: "approved",
      approval_id: "apv_1",
      ok: true,
      cached: false,
      result: { status: "return requested" },
      arguments: { order_id: "#W1" },
    }),
    event("model.called", 43, "support", {
      seconds: 1.4,
      pass: 3,
      message_id: "m3",
      model: "claude-sonnet-5",
      usage,
      tools: [],
    }),
    event("ticket.replied", 43.1, "support", {
      citations: ["policy-returns@v1#2"],
      citation_problems: [],
    }),
  ]
}

const THREAD: ThreadView = {
  channels: {
    support: [
      {
        id: "tk#0",
        kind: "customer",
        text: "Return my order, please.",
        tool_calls: [],
      },
      {
        id: "m1",
        kind: "model",
        text: "",
        reasoning: "Authenticate first.",
        tool_calls: [
          {
            id: "c1",
            name: "find_user_id_by_email",
            arguments: { email: "ada@example.com" },
          },
        ],
      },
      {
        id: "t1",
        kind: "tool",
        text: "ada_1",
        tool_call_id: "c1",
        tool: "find_user_id_by_email",
        ok: true,
        tool_calls: [],
      },
      {
        id: "m2",
        kind: "model",
        text: "",
        reasoning: null,
        tool_calls: [
          {
            id: "c2",
            name: "return_delivered_order_items",
            arguments: { order_id: "#W1" },
          },
        ],
      },
      {
        id: "t2",
        kind: "tool",
        text: '{"status": "return requested"}',
        tool_call_id: "c2",
        tool: "return_delivered_order_items",
        ok: true,
        tool_calls: [],
      },
      {
        id: "m3",
        kind: "model",
        text: JSON.stringify({
          reply: "Done.",
          citations: ["policy-returns@v1#2"],
          status: "resolved",
          summary: "Returned.",
        }),
        reasoning: "Confirm it.",
        tool_calls: [],
      },
    ],
  },
  route: null,
  screening: null,
  outputs: {},
  retrieved: [],
  versions: {},
  verified_customer_id: "ada_1",
}

describe("a run, pass by pass", () => {
  const inspection = inspect(ticketRun(), THREAD)

  it("joins each model call to its message, its reasoning and the calls it asked for", () => {
    expect(inspection.passes.map((p) => [p.key, p.reasoning])).toEqual([
      ["support:1", "Authenticate first."],
      ["support:2", null],
      ["support:3", "Confirm it."],
    ])
    const [first] = inspection.passes
    expect(first.calls[0]).toMatchObject({
      tool: "find_user_id_by_email",
      verdict: "allowed",
      summary: "ada_1",
      output: "ada_1",
    })
    expect(first.input).toBe(5400)
    expect(first.cached).toBe(5000)
    expect(first.context.map((m) => m.kind)).toEqual(["customer"])
  })

  it("ties an approval to the call that waited for it", () => {
    const call = inspection.passes[1].calls[0]
    expect(call.verdict).toBe("approved")
    expect(call.approval).toMatchObject({
      approvalId: "apv_1",
      requestedAt: 6200,
      decidedAt: 40_000,
      verdict: "approve",
    })
  })

  it("reads the final answer and what came before the loop", () => {
    expect(inspection.passes[2].answer).toMatchObject({
      status: "resolved",
      reply: "Done.",
      citations: ["policy-returns@v1#2"],
    })
    expect(inspection.screening).toMatchObject({
      blocked: false,
      reason: "An ordinary request.",
      seconds: 0.6,
    })
    expect(inspection.route).toMatchObject({
      route: "support",
      reason: "An order request.",
      seconds: 0.8,
    })
    expect(inspection.citations).toEqual({
      cited: ["policy-returns@v1#2"],
      problems: [],
    })
    expect(inspection.entries[0]).toMatchObject({
      kind: "customer",
      opening: true,
    })
    expect(inspection.lanes.map((lane) => lane.label)).toEqual([
      "Input check",
      "Dispatcher",
      "Support: model",
      "Support: tools",
      "You",
      "Customer",
    ])
  })

  it("reads the answer from a reply call, and leaves it out of the calls", () => {
    const events = ticketRun().map((e) =>
      e.kind === "model.called" && e.payload?.pass === 3
        ? {
            ...e,
            payload: { ...e.payload, tools: [{ id: "c3", name: REPLY_TOOL }] },
          }
        : e
    )
    const answer = {
      reply: "Done.",
      citations: ["policy-returns@v1#2"],
      status: "resolved",
      summary: "Returned.",
    }
    const support = THREAD.channels.support.map((m) =>
      m.id === "m3"
        ? {
            ...m,
            text: "",
            tool_calls: [{ id: "c3", name: REPLY_TOOL, arguments: answer }],
          }
        : m
    )
    const replied = inspect(events, {
      ...THREAD,
      channels: { support },
    })
    expect(replied.passes[2].answer).toMatchObject({
      reply: "Done.",
      status: "resolved",
    })
    expect(replied.passes[2].calls).toEqual([])
  })

  it("shows a call still waiting for approval as not run yet", () => {
    const events = ticketRun().slice(0, 8)
    const waiting = inspect(events, THREAD, T0 + 20_000)
    const call = waiting.passes[1].calls[0]
    expect(call.verdict).toBe("pending")
    expect(call.approval?.decidedAt).toBeNull()
    const you = waiting.lanes.find((lane) => lane.key === "you")
    expect(you?.bars[0]).toMatchObject({ start: 6200, end: 20_000 })
  })

  it("reads a typed answer only when it is a JSON object", () => {
    expect(answerOf("not json")).toBeNull()
    expect(answerOf("[1, 2]")).toBeNull()
    expect(answerOf('{"title": "x"}')?.fields.title).toBe("x")
  })
})

describe("the folded time axis", () => {
  it("folds a long quiet stretch so the steps either side keep their width", () => {
    const lanes = [
      {
        key: "a",
        label: "a",
        bars: [
          { start: 0, end: 1000, tone: "agent" as const },
          { start: 60_000, end: 61_000, tone: "agent" as const },
        ],
        marks: [],
      },
    ]
    const axis = foldedAxis(lanes, 240)
    expect(axis.folds).toHaveLength(1)
    expect(axis.toX(0)).toBe(0)
    expect(axis.toX(1000)).toBeCloseTo(100)
    expect(axis.toX(60_000)).toBeCloseTo(140)
    expect(axis.toX(61_000)).toBeCloseTo(240)
  })
})

describe("how an incident unfolded", () => {
  it("runs from the alert through the team to the replies that cited what it published", () => {
    nextId = 1
    const alert = [
      event("work.created", 0, "monitor", { kind: "alert" }, "wi_a"),
      event(
        "work.routed",
        1,
        "dispatcher",
        { route: "ops", reason: "An alert." },
        "wi_a"
      ),
      event("model.called", 3, "ops", { seconds: 1 }, "wi_a"),
      event("tool.called", 4, "ops", { tool: "analytics_run_sql" }, "wi_a"),
      event(
        "incident.filed",
        6,
        "ops",
        { title: "Northstar late", severity: "high" },
        "wi_a"
      ),
      event(
        "agent.handoff",
        6.5,
        "ops",
        { from: "ops", to: "insights", brief: "Draft a notice." },
        "wi_a"
      ),
      event(
        "tool.called",
        8,
        "insights",
        { tool: "knowledge_draft_article", arguments: { doc_id: "notice" } },
        "wi_a"
      ),
      event(
        "proposal.created",
        9,
        "insights",
        {
          proposal_id: "prp_1",
          title: "Publish the notice",
          kind: "kb_article",
        },
        "wi_a"
      ),
      event(
        "proposal.decided",
        30,
        "operator",
        { proposal_id: "prp_1", verdict: "approved" },
        "wi_a"
      ),
      event(
        "kb.published",
        30.1,
        "operator",
        { doc_id: "notice", version: 1, effective_date: "2026-06-15" },
        "wi_a"
      ),
    ]
    const later = [
      event(
        "ticket.replied",
        50,
        "support",
        {
          citations: ["notice@v1#0"],
          reply: "Your parcel is late.",
          ticket_id: "tk_9",
        },
        "wi_t"
      ),
      event(
        "ticket.replied",
        51,
        "support",
        { citations: ["other@v2#1"] },
        "wi_u"
      ),
    ]
    const steps = incidentChain(alert, later, [] as ProposalRecord[])
    expect(steps.map((step) => step.title)).toEqual([
      "The hourly delivery check raised an alert, and it became work for the team",
      "Ops looked into it: 1 model call, 1 tool call",
      "Ops filed the incident: Northstar late",
      "Ops handed it to Insights",
      "Insights worked on it: 1 tool call",
      "Insights proposed: Publish the notice",
      'You approved "a proposal"',
      "Published notice v1 to the knowledge base",
      "Support cited it in 1 reply afterwards",
    ])
    expect(steps.at(-1)?.links).toEqual([{ href: "/runs/wi_t", label: "tk_9" }])
  })
})

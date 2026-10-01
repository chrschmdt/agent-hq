import { describe, expect, it } from "vitest"

import type {
  PathStep,
  ReviewRecord,
  SearchResult,
  WorkItem,
} from "@/lib/api/types"
import { detailHref, isDetail } from "@/lib/drawer"
import { runRoute, travelled } from "@/lib/flow/run"
import { ago, sentence, usd } from "@/lib/format"
import { queriesFor } from "@/lib/live/invalidate"
import {
  agreement,
  comparison,
  diffLines,
  metricText,
  versionActions,
} from "@/lib/management"
import { blocks, spans } from "@/lib/markdown"
import { bumpLines, passagesById } from "@/lib/retrieval"
import { changed, fieldsOf, toArguments, toValues } from "@/lib/schema-form"
import { agentTicketsError } from "@/lib/sim"
import { byColumn, workDetail, workTitle } from "@/lib/work"

const NOW = "2026-06-15T15:00:00Z"

function work(
  kind: WorkItem["kind"],
  status: WorkItem["status"],
  input: Record<string, unknown> = {}
): WorkItem {
  return {
    id: `wi_${kind}_${status}`,
    kind,
    status,
    thread_id: "th",
    input: input as WorkItem["input"],
    owner: null,
    attempts: 0,
    last_error: null,
    created_at: NOW,
    updated_at: NOW,
  }
}

function step(node: string): PathStep {
  return {
    node,
    started_at: NOW,
    ended_at: NOW,
    first_event_id: 1,
    last_event_id: 1,
    model_calls: 0,
    tool_calls: 0,
    cost_usd: 0,
    waited_for_approval: false,
  }
}

describe("the work board", () => {
  it("names work by what it is about", () => {
    expect(workTitle(work("ticket", "done", { ticket_id: "tk_1" }))).toBe(
      "Ticket tk_1"
    )
    const alert = work("alert", "done", {
      alert: {
        metric: "where_is_my_order_tickets",
        segment: { carrier: "northstar", region: "northeast" },
        value: 6,
        baseline: 0.42,
        window_hours: 3,
      },
    })
    expect(workTitle(alert)).toBe("Alert: northstar, northeast")
    expect(workDetail(alert)).toBe(
      "6 where is my order tickets in 3 hours, 0.4 expected"
    )
    expect(
      workTitle(work("flag", "new", { flag: { topic: "delivery" } }))
    ).toBe("Flag: delivery")
  })

  it("puts each status in one column", () => {
    const columns = byColumn([
      work("ticket", "running"),
      work("ticket", "waiting_approval"),
      work("alert", "failed"),
    ])
    expect(columns.active).toHaveLength(1)
    expect(columns.approval).toHaveLength(1)
    expect(columns.stopped).toHaveLength(1)
    expect(columns.done).toHaveLength(0)
  })
})

describe("a run's route", () => {
  it("goes in at entry and out through finalize once the work ends", () => {
    const route = runRoute(
      [step("dispatcher"), step("ops"), step("insights")],
      "done"
    )
    expect(route).toEqual([
      "__start__",
      "entry",
      "screen",
      "dispatcher",
      "ops",
      "insights",
      "finalize",
      "__end__",
    ])
    expect(travelled(route).has("ops->insights")).toBe(true)
  })

  it("enters again for each customer turn", () => {
    const route = runRoute(
      [step("support"), step("finalize"), step("support"), step("finalize")],
      "waiting_customer"
    )
    expect(route.filter((node) => node === "entry")).toHaveLength(2)
    expect(route.at(-1)).toBe("__end__")
  })

  it("passes the input check once, whether or not it recorded a step", () => {
    const route = runRoute([step("screen"), step("human")], "escalated")
    expect(route.filter((node) => node === "screen")).toHaveLength(1)
    expect(travelled(route).has("screen->human")).toBe(true)
  })

  it("stays open while the work waits for approval", () => {
    expect(runRoute([step("support")], "waiting_approval").at(-1)).toBe(
      "support"
    )
  })
})

describe("the approval form", () => {
  const parameters = {
    properties: {
      order_id: { type: "string", description: "The order" },
      item_ids: { type: "array", items: { type: "string" } },
      amount: { anyOf: [{ type: "number" }, { type: "null" }] },
      address: { type: "object" },
    },
    required: ["order_id", "item_ids"],
  }

  it("round-trips arguments through the fields", () => {
    const fields = fieldsOf(parameters)
    expect(fields.map((field) => field.kind)).toEqual([
      "text",
      "list",
      "number",
      "json",
    ])
    const args = {
      order_id: "#W1",
      item_ids: ["1", "2"],
      amount: 12.5,
      address: { city: "Austin" },
    }
    const back = toArguments(fields, toValues(fields, args))
    expect(back).toEqual({ ok: true, args })
    expect(changed(args, { ...args, item_ids: ["1"] })).toBe(true)
    expect(
      changed(args, {
        address: { city: "Austin" },
        amount: 12.5,
        item_ids: ["1", "2"],
        order_id: "#W1",
      })
    ).toBe(false)
  })

  it("reports what is missing or malformed", () => {
    const fields = fieldsOf(parameters)
    expect(toArguments(fields, { order_id: "", item_ids: "1" })).toEqual({
      ok: false,
      error: "order id is required.",
    })
    expect(
      toArguments(fields, { order_id: "#W1", item_ids: "1", amount: "lots" })
    ).toMatchObject({ ok: false })
    expect(
      toArguments(fields, { order_id: "#W1", item_ids: "1, 2", address: "{" })
    ).toMatchObject({ ok: false })
  })
})

describe("articles", () => {
  it("splits markdown into headings, paragraphs and lists", () => {
    const parsed = blocks(
      "# Title\n\nIntro line\ncontinues.\n\n## Steps\n\n1. One\n2. Two\n- a\n- b"
    )
    expect(parsed.map((block) => block.kind)).toEqual([
      "heading",
      "paragraph",
      "heading",
      "list",
      "list",
    ])
    expect(parsed[1]).toEqual({
      kind: "paragraph",
      text: "Intro line continues.",
    })
    expect(parsed[3]).toEqual({
      kind: "list",
      ordered: true,
      items: ["One", "Two"],
    })
  })

  it("marks bold and code inside a line", () => {
    expect(spans("Use **#W** and `code` here")).toEqual([
      { text: "Use " },
      { text: "#W", bold: true },
      { text: " and " },
      { text: "code", code: true },
      { text: " here" },
    ])
  })
})

describe("the retrieval inspector", () => {
  const passage = (id: string) => ({
    passage_id: id,
    doc_id: id,
    title: id,
    section: "s",
    namespace: "policy" as const,
    version: 1,
    effective_date: "2026-01-01",
    valid_until: "9999-12-31",
    text: "",
    score: 0,
  })
  const result: SearchResult = {
    mode: "hybrid_rerank",
    passages: [passage("b")],
    trace: {
      dense: [
        { passage_id: "a", score: 1 },
        { passage_id: "b", score: 0.5 },
      ],
      bm25: [{ passage_id: "b", score: 3 }],
      fused: [
        { passage_id: "b", score: 0.03 },
        { passage_id: "a", score: 0.02 },
      ],
      reranked: [{ passage_id: "b", score: 0.9 }],
      candidates: [passage("a"), passage("b")],
    },
  }

  it("ranks each passage at every stage it reached", () => {
    expect(bumpLines(result)).toEqual([
      { passageId: "a", ranks: [1, null, 2, null], final: false },
      { passageId: "b", ranks: [2, 1, 1, 1], final: true },
    ])
    expect([...passagesById(result).keys()]).toEqual(["a", "b"])
  })
})

describe("formatting and refreshing", () => {
  it("writes values for people", () => {
    expect(sentence("return_delivered_order_items")).toBe(
      "Return delivered order items"
    )
    expect(usd(0)).toBe("$0")
    expect(usd(0.0042)).toBe("$0.0042")
    expect(usd(12.5)).toBe("$12.50")
    expect(ago("2026-06-15T14:58:00Z", Date.parse(NOW))).toBe("2m ago")
  })

  it("refreshes the screens an event can change", () => {
    expect(queriesFor("approval.decided")).toContain("approvals")
    expect(queriesFor("proposal.created")).toContain("proposals")
    expect(queriesFor("parcel.delivered")).toEqual([])
    expect(queriesFor("version.rolled_back")).toContain("scorecards")
    expect(queriesFor("breaker.opened")).toContain("limits")
  })
})

describe("management", () => {
  const rate = {
    key: "escalation_rate",
    label: "Escalation rate",
    category: "outcome",
    direction: "lower",
    unit: "rate",
    min_samples: 5,
  } as const
  const cost = {
    ...rate,
    key: "cost_per_run",
    unit: "usd",
    direction: "lower",
  } as const

  it("formats metrics by their unit", () => {
    expect(metricText({ key: "x", value: 0.125, samples: 8 }, rate)).toBe(
      "12.5%"
    )
    expect(metricText({ key: "x", value: 0.004, samples: 8 }, cost)).toBe(
      "$0.0040"
    )
    expect(metricText({ key: "x", value: null, samples: 0 }, rate)).toBe("-")
  })

  it("says whether a value is better given the metric's direction", () => {
    expect(comparison(rate, 0.1, 0.3)).toBe("better")
    expect(comparison(rate, 0.3, 0.1)).toBe("worse")
    expect(comparison(rate, 0.3, 0.305)).toBe("same")
    expect(comparison(cost, 0.02, 0.01)).toBe("worse")
    expect(comparison(rate, null, 0.1)).toBeNull()
  })

  it("classifies diff lines", () => {
    expect(
      diffLines(["--- a", "+++ b", "@@ -1 +1 @@", " same", "-old", "+new"]).map(
        (line) => line.kind
      )
    ).toEqual(["file", "file", "hunk", "same", "remove", "add"])
  })

  it("compares a person's labels with the reviewer's verdicts", () => {
    const review = {
      criteria: [
        { criterion_id: "tone", critique: "", verdict: "pass" },
        { criterion_id: "policy", critique: "", verdict: "fail" },
      ],
    } as unknown as ReviewRecord
    expect(agreement({ tone: "pass", policy: "pass" }, review)).toEqual({
      tone: true,
      policy: false,
    })
  })

  it("offers only the moves a status allows", () => {
    expect(versionActions("live")).toEqual([])
    expect(versionActions("canary")).toEqual(["promote", "rollback"])
    expect(versionActions("retired")).toEqual(["canary"])
  })
})

describe("simulator", () => {
  it("takes up to 200 tickets for the agents and says why it refuses more", () => {
    expect(agentTicketsError("0")).toBeNull()
    expect(agentTicketsError(" 200 ")).toBeNull()
    expect(agentTicketsError("201")).toBe(
      "The agents can take at most 200 tickets."
    )
    expect(agentTicketsError("")).toBe("Enter a whole number of tickets.")
    expect(agentTicketsError("-1")).toBe("Enter a whole number of tickets.")
    expect(agentTicketsError("2.5")).toBe("Enter a whole number of tickets.")
  })
})

describe("drawer", () => {
  it("opens the team's records wide and links to them through their list page", () => {
    expect(isDetail({ kind: "incident", id: "inc_1" })).toBe(true)
    expect(isDetail({ kind: "order", id: "#W1234567" })).toBe(false)
    expect(detailHref({ kind: "approval", id: "apv_1" })).toBe(
      "/approvals?open=apv_1"
    )
    expect(detailHref({ kind: "proposal", id: "prp 1" })).toBe(
      "/proposals?open=prp%201"
    )
  })
})

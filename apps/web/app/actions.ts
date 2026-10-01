"use server"

import { revalidatePath } from "next/cache"

import { currentSession, signIn, signInProvider, signOut } from "@/auth"
import { CACHED, forget } from "@/lib/api/cached"
import { operatorApi } from "@/lib/api/operator"
import type {
  ActivityReport,
  AgentVersion,
  ApprovalDecision,
  Customer,
  EvalRun,
  LabelOutcome,
  ModelsView,
  OrderView,
  RecordingInfo,
  SearchResult,
  SimilarTicket,
  SimRun,
  Ticket,
  TraceProject,
  VersionConfig,
} from "@/lib/api/types"

export type ActionResult<T> =
  { ok: true; data: T } | { ok: false; error: string }

const NOT_ADMIN = "Sign in as the admin to do this."

async function asAdmin<T>(
  run: () => Promise<{ data?: T; error?: unknown; response: Response }>
): Promise<ActionResult<T>> {
  if (!(await currentSession())) {
    return { ok: false, error: NOT_ADMIN }
  }
  const { data, error, response } = await run()
  if (data === undefined || error !== undefined) {
    return { ok: false, error: describe(error, response) }
  }
  return { ok: true, data }
}

function forgetting<T>(
  result: ActionResult<T>,
  ...tags: (typeof CACHED)[keyof typeof CACHED][]
): ActionResult<T> {
  if (result.ok) {
    forget(...tags)
  }
  return result
}

function describe(error: unknown, response: Response): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail
    return typeof detail === "string" ? detail : JSON.stringify(detail)
  }
  return `The api answered ${response.status}.`
}

export async function signInAction(): Promise<void> {
  if (signInProvider !== null) {
    await signIn(signInProvider, { redirectTo: "/overview" })
  }
}

export async function signOutAction(): Promise<void> {
  await signOut({ redirectTo: "/overview" })
}

export async function decideApproval(
  approvalId: string,
  decision: ApprovalDecision
): Promise<ActionResult<unknown>> {
  const result = await asAdmin(() =>
    operatorApi.POST("/api/approvals/{approval_id}/decision", {
      params: { path: { approval_id: approvalId } },
      body: decision,
    })
  )
  revalidatePath("/approvals")
  return result
}

export async function decideProposal(
  proposalId: string,
  verdict: "approved" | "rejected",
  note: string | null
): Promise<ActionResult<unknown>> {
  const result = await asAdmin(() =>
    operatorApi.POST("/api/proposals/{proposal_id}/decision", {
      params: { path: { proposal_id: proposalId } },
      body: { verdict, note },
    })
  )
  revalidatePath("/proposals")
  return result
}

export async function startSimulation(options: {
  scenario: string
  seed: number
  agent_tickets: number
  alerts_to_agents: boolean
  tick_seconds: number
}): Promise<ActionResult<SimRun>> {
  return asAdmin(() =>
    operatorApi.POST("/api/sim/start", {
      body: { tick_minutes: 5, ...options },
    })
  )
}

export async function controlSimulation(
  runId: string,
  action: "pause" | "resume" | "stop"
): Promise<ActionResult<SimRun>> {
  const path = { params: { path: { run_id: runId } } }
  return asAdmin(() => {
    switch (action) {
      case "pause":
        return operatorApi.POST("/api/sim/{run_id}/pause", path)
      case "resume":
        return operatorApi.POST("/api/sim/{run_id}/resume", path)
      case "stop":
        return operatorApi.POST("/api/sim/{run_id}/stop", path)
    }
  })
}

export async function resetSimulation(): Promise<ActionResult<unknown>> {
  return asAdmin(() => operatorApi.POST("/api/sim/reset"))
}

export async function searchKnowledge(query: {
  query: string
  audience: "customer" | "internal"
  k: number
}): Promise<ActionResult<SearchResult>> {
  return asAdmin(() =>
    operatorApi.POST("/api/retrieval/search", {
      body: { ...query, namespaces: [], as_of: null },
    })
  )
}

export async function findSimilarTickets(query: {
  text: string
  days: number
  intent: string | null
}): Promise<ActionResult<SimilarTicket[]>> {
  return asAdmin(() =>
    operatorApi.POST("/api/analytics/similar-tickets", {
      body: { ...query, limit: 10 },
    })
  )
}

export async function writeAsCustomer(
  workItemId: string,
  text: string
): Promise<ActionResult<unknown>> {
  return asAdmin(() =>
    operatorApi.POST("/api/work/{work_item_id}/messages", {
      params: { path: { work_item_id: workItemId } },
      body: { text },
    })
  )
}

export async function openTicket(
  message: string
): Promise<ActionResult<unknown>> {
  return asAdmin(() => operatorApi.POST("/api/tickets", { body: { message } }))
}

export async function cancelWork(
  workItemId: string,
  reason: string
): Promise<ActionResult<unknown>> {
  return asAdmin(() =>
    operatorApi.POST("/api/work/{work_item_id}/cancel", {
      params: { path: { work_item_id: workItemId } },
      body: { reason },
    })
  )
}

export async function createVersion(
  agent: string,
  config: VersionConfig,
  note: string
): Promise<ActionResult<AgentVersion>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/agents/{agent}/versions", {
        params: { path: { agent } },
        body: { config, note },
      })
    ),
    CACHED.versions
  )
}

export async function requestGate(
  versionId: string
): Promise<ActionResult<EvalRun>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/versions/{version_id}/gate", {
        params: { path: { version_id: versionId } },
      })
    ),
    CACHED.evals,
    CACHED.versions
  )
}

export async function startCanary(
  versionId: string,
  pct: number,
  skipGate: boolean
): Promise<ActionResult<AgentVersion>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/versions/{version_id}/canary", {
        params: { path: { version_id: versionId } },
        body: { pct, skip_gate: skipGate },
      })
    ),
    CACHED.versions
  )
}

export async function promoteVersion(
  versionId: string,
  reason: string,
  force: boolean
): Promise<ActionResult<AgentVersion>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/versions/{version_id}/promote", {
        params: { path: { version_id: versionId } },
        body: { reason, force },
      })
    ),
    CACHED.versions
  )
}

export async function rollBackVersion(
  versionId: string,
  reason: string
): Promise<ActionResult<AgentVersion>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/versions/{version_id}/rollback", {
        params: { path: { version_id: versionId } },
        body: { reason },
      })
    ),
    CACHED.versions
  )
}

export async function retireVersion(
  versionId: string,
  reason: string
): Promise<ActionResult<AgentVersion>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/versions/{version_id}/retire", {
        params: { path: { version_id: versionId } },
        body: { reason },
      })
    ),
    CACHED.versions
  )
}

export async function pauseAgent(
  agent: string,
  reason: string
): Promise<ActionResult<unknown>> {
  return asAdmin(() =>
    operatorApi.POST("/api/agents/{agent}/pause", {
      params: { path: { agent } },
      body: { reason },
    })
  )
}

export async function resumeAgent(
  agent: string
): Promise<ActionResult<unknown>> {
  return asAdmin(() =>
    operatorApi.POST("/api/agents/{agent}/resume", {
      params: { path: { agent } },
    })
  )
}

export async function labelRun(
  workItemId: string,
  agent: string,
  verdicts: Record<string, "pass" | "fail">
): Promise<ActionResult<LabelOutcome>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/qa/labels", {
        body: { work_item_id: workItemId, agent, verdicts },
      })
    ),
    CACHED.calibration
  )
}

export async function requestReview(
  workItemId: string,
  agent: string
): Promise<ActionResult<unknown>> {
  return asAdmin(() =>
    operatorApi.POST("/api/qa/reviews", {
      body: { work_item_id: workItemId, agent },
    })
  )
}

export async function chooseProfile(
  profile: ModelsView["profile"]
): Promise<ActionResult<ModelsView>> {
  return asAdmin(() =>
    operatorApi.PUT("/api/models/profile", { body: { profile } })
  )
}

export async function recordDay(
  simRunId: string,
  title: string | null
): Promise<ActionResult<RecordingInfo>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/recordings", {
        body: { sim_run_id: simRunId, title },
      })
    ),
    CACHED.recordings
  )
}

export async function changeRecording(
  recordingId: string,
  change: { published?: boolean; title?: string }
): Promise<ActionResult<RecordingInfo>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.PATCH("/api/recordings/{recording_id}", {
        params: { path: { recording_id: recordingId } },
        body: change,
      })
    ),
    CACHED.recordings
  )
}

export async function deleteRecording(
  recordingId: string
): Promise<ActionResult<null>> {
  if (!(await currentSession())) {
    return { ok: false, error: NOT_ADMIN }
  }
  const { error, response } = await operatorApi.DELETE(
    "/api/recordings/{recording_id}",
    { params: { path: { recording_id: recordingId } } }
  )
  return forgetting(
    error === undefined
      ? { ok: true, data: null }
      : { ok: false, error: describe(error, response) },
    CACHED.recordings
  )
}

export async function clearActivity(
  versions: boolean
): Promise<ActionResult<ActivityReport>> {
  return forgetting(
    await asAdmin(() =>
      operatorApi.POST("/api/activity/clear", { body: { versions } })
    ),
    CACHED.evals,
    CACHED.calibration,
    CACHED.versions
  )
}

export async function readOrder(
  orderId: string
): Promise<ActionResult<OrderView>> {
  return asAdmin(() =>
    operatorApi.GET("/api/store/orders/{order_id}", {
      params: { path: { order_id: orderId } },
    })
  )
}

export async function readCustomer(
  userId: string
): Promise<ActionResult<Customer>> {
  return asAdmin(() =>
    operatorApi.GET("/api/store/customers/{user_id}", {
      params: { path: { user_id: userId } },
    })
  )
}

export async function readTicket(
  ticketId: string
): Promise<ActionResult<Ticket>> {
  return asAdmin(() =>
    operatorApi.GET("/api/tickets/{ticket_id}", {
      params: { path: { ticket_id: ticketId } },
    })
  )
}

export async function readTraceProject(): Promise<ActionResult<TraceProject>> {
  return asAdmin(() => operatorApi.GET("/api/traces/project"))
}

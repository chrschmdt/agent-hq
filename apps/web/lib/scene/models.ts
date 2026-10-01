import type { Lineup } from "@/lib/api/types"

export type ModelRow = {
  id: string
  title: string
  provider: string
  roles: string[]
  reasoning: boolean
}

export const ROLES = [
  "guard",
  "dispatcher",
  "support",
  "ops",
  "insights",
  "customer",
  "qa",
] as const
export type Role = (typeof ROLES)[number]

export const RETRIEVAL_ROW = "voyage"

const ROLE_NAMES: Record<Role, string> = {
  guard: "input check",
  dispatcher: "Dispatcher",
  support: "Support",
  ops: "Ops",
  insights: "Insights",
  customer: "simulated customers",
  qa: "QA reviewer",
}

const MODEL_TITLES: Record<string, string> = {
  "claude-haiku-4-5": "Haiku 4.5",
  "claude-sonnet-5": "Sonnet 5",
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-opus-5-5": "Opus 5.5",
}

const PROVIDERS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  voyageai: "Voyage",
  fake: "offline",
}

const RULE_GROUPS: Record<Role, string> = {
  guard: "rules:triage",
  dispatcher: "rules:triage",
  support: "rules:agents",
  ops: "rules:agents",
  insights: "rules:agents",
  customer: "rules:customers",
  qa: "rules:qa",
}

export type Rail = { rows: ModelRow[]; rowOf: (role: string) => string }

export function modelRail(lineup: Lineup | null | undefined): Rail {
  const rows: ModelRow[] = []
  const byRole = new Map<string, string>()
  for (const role of ROLES) {
    const model = lineup?.roles[role]
    const id = !model
      ? `role:${role}`
      : model.key === "fake"
        ? RULE_GROUPS[role]
        : model.key
    byRole.set(role, id)
    const row = rows.find((existing) => existing.id === id)
    if (row) {
      row.roles.push(ROLE_NAMES[role])
      continue
    }
    rows.push({
      id,
      title: !model
        ? ROLE_NAMES[role]
        : model.key === "fake"
          ? "Rules"
          : (MODEL_TITLES[model.key] ?? model.key),
      provider: model ? (PROVIDERS[model.provider] ?? model.provider) : "",
      roles: [ROLE_NAMES[role]],
      reasoning: model?.reasoning ?? false,
    })
  }
  const embeddings = lineup?.embeddings.replace(/^voyageai\//, "") ?? "voyage-4"
  const rerank = lineup?.rerank.replace(/^voyageai\//, "") ?? "rerank-2.5"
  rows.push({
    id: RETRIEVAL_ROW,
    title: `${embeddings}, ${rerank}`,
    provider: "Voyage",
    roles: ["knowledge search"],
    reasoning: false,
  })
  return {
    rows,
    rowOf: (role) => byRole.get(role) ?? `role:${role}`,
  }
}

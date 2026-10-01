import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { AgentDetail, ToolInfo } from "@/lib/api/types"
import { usd } from "@/lib/format"
import { cn } from "@/lib/utils"

const LEVELS = [
  { key: "observe", label: "Observe", means: "reads and answers" },
  { key: "draft", label: "Draft", means: "also drafts for review" },
  { key: "act", label: "Act", means: "also changes the store" },
] as const

const SERVERS: Record<string, string> = {
  orders: "Orders",
  knowledge: "Knowledge",
  analytics: "Analytics",
}

const EFFECT: Record<string, string> = {
  read: "border-[color-mix(in_oklch,var(--map-live)_55%,transparent)] text-foreground",
  write:
    "border-[var(--map-amber)] bg-[color-mix(in_oklch,var(--map-amber)_10%,transparent)] text-foreground",
  draft:
    "border-[var(--map-violet)] bg-[color-mix(in_oklch,var(--map-violet)_10%,transparent)] text-foreground",
  generic: "border-border text-foreground",
}

function approval(tool: ToolInfo): string | null {
  if (tool.exception) {
    return "always waits for you"
  }
  if (tool.refund_gated) {
    return "waits for you over the refund limit"
  }
  return null
}

const tokens = (chars: number) => Math.round(chars / 4)

export function AgentGlance({ agent }: { agent: AgentDetail }) {
  const level = LEVELS.findIndex((l) => l.key === agent.autonomy)
  const servers = new Map<string, ToolInfo[]>()
  for (const tool of agent.tool_details) {
    servers.set(tool.server, [...(servers.get(tool.server) ?? []), tool])
  }
  const groups = [...servers.values()].map((tools) => tools.length)
  if (agent.can_flag) {
    groups.push(1)
  }
  const columns = groups
    .map((tools) => `minmax(0,${Math.max(1, Math.ceil(tools / 4))}fr)`)
    .join(" ")
  const stable = agent.prompt_stable.length
  const context = agent.prompt_context.length
  const share = stable + context > 0 ? (stable / (stable + context)) * 100 : 0
  return (
    <Card>
      <CardHeader>
        <CardTitle>At a glance</CardTitle>
        <CardDescription>
          What the agent may do, what it can reach, and how its prompt is built.
          Limits per work item: {agent.max_model_calls} model calls and{" "}
          {usd(agent.max_usd)}.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground">Autonomy</span>
          <div className="grid grid-cols-3 gap-1.5">
            {LEVELS.map((step, index) => (
              <div
                key={step.key}
                className={cn(
                  "rounded-lg border px-3 py-2",
                  index <= level
                    ? "border-[color-mix(in_oklch,var(--map-live)_55%,transparent)] bg-[color-mix(in_oklch,var(--map-live)_10%,transparent)]"
                    : "text-muted-foreground"
                )}
              >
                <p className="text-sm font-semibold">
                  L{index} {step.label}
                </p>
                <p className="text-xs text-muted-foreground">{step.means}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground">
            Tools, by the server behind them.{" "}
            {agent.customer_scoped
              ? "Scoped to the one customer it has verified."
              : "Store-wide, read-only data."}
          </span>
          {agent.tool_details.length === 0 && !agent.can_flag ? (
            <p className="text-sm text-muted-foreground">
              None: one typed answer, no tools.
            </p>
          ) : (
            <div
              className="grid gap-3 md:grid-cols-(--groups)"
              style={{ "--groups": columns } as React.CSSProperties}
            >
              {[...servers.entries()].map(([server, tools]) => (
                <div
                  key={server}
                  className="flex min-w-0 flex-col gap-1.5 rounded-lg border bg-muted/20 p-2.5"
                >
                  <span className="text-xs font-semibold">
                    {SERVERS[server] ?? server}
                  </span>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,13rem),1fr))] gap-1.5">
                    {tools.map((tool) => {
                      const waits = approval(tool)
                      return (
                        <span
                          key={tool.name}
                          title={tool.description}
                          className={cn(
                            "flex flex-col rounded-md border px-2 py-1",
                            EFFECT[tool.effect] ?? EFFECT.generic
                          )}
                        >
                          <span className="font-mono text-[11px] wrap-anywhere">
                            {tool.name}
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {tool.effect}
                            {waits ? `, ${waits}` : ""}
                          </span>
                        </span>
                      )
                    })}
                  </div>
                </div>
              ))}
              {agent.can_flag ? (
                <div className="flex min-w-0 flex-col gap-1.5 rounded-lg border bg-muted/20 p-2.5">
                  <span className="text-xs font-semibold">Team graph</span>
                  <span
                    className={cn(
                      "flex flex-col rounded-md border px-2 py-1",
                      EFFECT.generic
                    )}
                  >
                    <span className="font-mono text-[11px]">flag_pattern</span>
                    <span className="text-[10px] text-muted-foreground">
                      starts work for the operations team
                    </span>
                  </span>
                </div>
              ) : null}
            </div>
          )}
          <div className="flex flex-wrap gap-4 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className={cn("size-3 rounded border", EFFECT.read)} />{" "}
              reads
            </span>
            <span className="flex items-center gap-1.5">
              <span className={cn("size-3 rounded border", EFFECT.write)} />{" "}
              changes the store
            </span>
            <span className="flex items-center gap-1.5">
              <span className={cn("size-3 rounded border", EFFECT.draft)} />{" "}
              drafts for review
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-xs text-muted-foreground">Prompt</span>
          <div className="flex h-3 overflow-hidden rounded">
            <span
              style={{
                width: `${share}%`,
                background:
                  "color-mix(in oklch, var(--map-live) 45%, var(--card))",
              }}
            />
            <span
              className="flex-1"
              style={{ background: "var(--map-live)" }}
            />
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            about {tokens(stable).toLocaleString("en-US")} tokens the same for
            every piece of work, so providers cache them · about{" "}
            {tokens(context).toLocaleString("en-US")} filled in per piece of
            work
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

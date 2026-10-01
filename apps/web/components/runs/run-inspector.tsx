"use client"

import { useQuery } from "@tanstack/react-query"
import { useMemo, useState, useTransition } from "react"
import { toast } from "sonner"

import { readTraceProject, writeAsCustomer } from "@/app/actions"
import { EventRow } from "@/components/feed/event-row"
import { LoopCard } from "@/components/runs/inspector/loop-card"
import { PassCard } from "@/components/runs/inspector/pass-card"
import { RunAgents } from "@/components/runs/run-agents"
import {
  BeforeLoopCard,
  ChecksCard,
  LimitsCard,
  ReviewCard,
} from "@/components/runs/inspector/side-cards"
import { TimelineCard } from "@/components/runs/inspector/timeline-card"
import { RunGraph } from "@/components/runs/run-graph"
import { useAdmin, useCanAct } from "@/components/shell/admin-context"
import { DrawerLink } from "@/components/shell/drawer-context"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Textarea } from "@/components/ui/textarea"
import { WorkStatusBadge } from "@/components/work/work-status"
import { api } from "@/lib/api/client"
import type {
  AgentSummary,
  RunView as Run,
  ThreadView,
  Ticket,
  Topology,
} from "@/lib/api/types"
import { useDay } from "@/components/recording/recording-provider"
import { LinkedText, RecordLink } from "@/components/records/record-drawer"
import { clock, moment, usd, words } from "@/lib/format"
import { inspect, name, type Pass } from "@/lib/inspector/passes"
import { cn } from "@/lib/utils"
import { workTitle } from "@/lib/work"

async function fetchRun(id: string): Promise<Run> {
  const { data } = await api.GET("/api/runs/{work_item_id}", {
    params: { path: { work_item_id: id } },
  })
  if (!data) {
    throw new Error(`could not load run ${id}`)
  }
  return data
}

async function fetchThread(id: string): Promise<ThreadView | null> {
  const { data } = await api.GET("/api/runs/{work_item_id}/thread", {
    params: { path: { work_item_id: id } },
  })
  return data ?? null
}

function Fact({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums">{children}</span>
    </div>
  )
}

function Transcript({
  ticket,
  workItemId,
  waiting,
}: {
  ticket: Ticket
  workItemId: string
  waiting: boolean
}) {
  const day = useDay()
  const admin = useCanAct()
  const [text, setText] = useState("")
  const [pending, startTransition] = useTransition()
  const send = () =>
    startTransition(async () => {
      const result = await writeAsCustomer(workItemId, text)
      if (result.ok) {
        setText("")
        toast.success("Sent as the customer; the agents answer shortly.")
      } else {
        toast.error(result.error)
      }
    })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversation</CardTitle>
        <CardDescription>
          {ticket.subject}, {words(ticket.status)}. Times are the store&apos;s.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {ticket.messages.map((message, index) => (
          <div
            key={index}
            className={cn(
              "max-w-[90%] rounded-2xl px-4 py-2 text-sm",
              message.author === "customer"
                ? "self-start bg-muted"
                : "self-end bg-primary/10"
            )}
          >
            <p className="mb-1 text-xs text-muted-foreground">
              {message.author}, {clock(day(message.created_at))}
            </p>
            <p className="whitespace-pre-wrap">
              <LinkedText text={message.body} />
            </p>
          </div>
        ))}
        {waiting && admin ? (
          <div className="flex flex-col gap-2 border-t pt-3">
            <Textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Write as the customer"
            />
            <Button
              onClick={send}
              disabled={pending || text.trim() === ""}
              className="self-end"
            >
              Send as the customer
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function firstSelected(passes: Pass[]): string | null {
  const waiting = passes.find((pass) =>
    pass.calls.some((call) => call.approval !== null)
  )
  return (waiting ?? passes[0])?.key ?? null
}

export function RunInspector({
  initial,
  initialThread,
  topology,
  agents,
  replay = false,
}: {
  initial: Run
  initialThread: ThreadView | null
  topology: Topology
  agents: AgentSummary[]
  replay?: boolean
}) {
  const day = useDay()
  const id = initial.item.id
  const liveRun = useQuery({
    queryKey: ["runs", id],
    queryFn: () => fetchRun(id),
    initialData: initial,
    enabled: !replay,
  })
  const liveThread = useQuery({
    queryKey: ["runs", id, "thread"],
    queryFn: () => fetchThread(id),
    initialData: initialThread,
    enabled: !replay,
  })
  const run = replay ? initial : liveRun.data
  const thread = replay ? initialThread : liveThread.data
  const admin = useAdmin()
  const traces = useQuery({
    queryKey: ["trace-project"],
    queryFn: readTraceProject,
    enabled: admin && !replay && run.traced,
    staleTime: Infinity,
  })
  const traceUrl = traces.data?.ok ? traces.data.data.url : null
  const [now] = useState(() => (replay ? null : Date.now()))
  const inspection = useMemo(
    () => inspect(run.events, thread, now),
    [run.events, thread, now]
  )
  const [selected, setSelected] = useState<string | null>(() =>
    firstSelected(inspection.passes)
  )
  const selectedPass = inspection.passes.find((pass) => pass.key === selected)
  const [agent, setAgent] = useState<string | null>(null)
  const shownAgent =
    agent ?? selectedPass?.agent ?? inspection.agents[0] ?? "support"
  const scale = Math.max(
    1,
    ...inspection.passes.map((pass) => pass.input + pass.output)
  )
  const item = run.item

  const select = (key: string) => {
    setSelected(key)
    setAgent(null)
    document
      .getElementById(`pass-${key}`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{item.kind}</Badge>
            {workTitle(item)}
            <WorkStatusBadge status={item.status} />
            {replay ? (
              <Badge variant="outline">from the recorded day</Badge>
            ) : null}
          </CardTitle>
          <CardDescription className="font-mono text-xs">
            {item.id}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-x-8 gap-y-3">
          <Fact label="Owner">
            {item.owner ? words(item.owner) : "not routed yet"}
          </Fact>
          <Fact label="Created">{moment(day(item.created_at))}</Fact>
          {typeof item.input?.ticket_id === "string" ? (
            <Fact label="Ticket">
              <RecordLink
                target={{ kind: "ticket", id: item.input.ticket_id }}
              />
            </Fact>
          ) : null}
          <Fact label="Model calls">{run.model_calls}</Fact>
          <Fact label="Tool calls">{run.tool_calls}</Fact>
          <Fact label="Cost">{usd(run.cost_usd)}</Fact>
          <Fact label="Agents">
            {inspection.agents.map(name).join(", ") || "none yet"}
          </Fact>
          <Fact label="Trace">
            {traceUrl ? (
              <a
                href={traceUrl}
                target="_blank"
                rel="noreferrer"
                className="underline underline-offset-4"
              >
                LangSmith, filter by {item.id}
              </a>
            ) : run.traced ? (
              "traced"
            ) : (
              "not sampled"
            )}
          </Fact>
          {item.last_error ? (
            <Fact label="Error">{item.last_error}</Fact>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Route through the team</CardTitle>
          <CardDescription>
            The team graph with the nodes this run visited, numbered by step.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RunGraph topology={topology} path={run.path} status={item.status} />
        </CardContent>
      </Card>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <TimelineCard
          inspection={inspection}
          selected={selected}
          onSelect={select}
        />
        {inspection.passes.length > 0 ? (
          <LoopCard
            passes={inspection.passes}
            agents={inspection.agents}
            agent={shownAgent}
            selected={selectedPass}
            onAgent={setAgent}
          />
        ) : null}
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <section className="flex min-w-0 flex-col gap-4" aria-label="Passes">
          {inspection.entries.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                No agent has worked on this yet.
              </CardContent>
            </Card>
          ) : null}
          {inspection.entries.map((entry, index) =>
            entry.kind === "pass" ? (
              <PassCard
                key={entry.pass.key}
                pass={entry.pass}
                origin={inspection.origin}
                selected={entry.pass.key === selected}
                scale={scale}
                limit={
                  agents.find((a) => a.name === entry.pass.agent)
                    ?.max_model_calls ?? null
                }
                onSelect={() => setSelected(entry.pass.key)}
              />
            ) : entry.kind === "customer" ? (
              <div
                key={`c${index}`}
                className="flex items-start gap-3 rounded-xl border border-dashed px-4 py-3"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                  C
                </span>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <p className="text-xs text-muted-foreground">
                    {entry.opening
                      ? "The customer opened the ticket"
                      : "The customer wrote back"}
                  </p>
                  <p className="text-sm whitespace-pre-wrap">{entry.text}</p>
                </div>
              </div>
            ) : (
              <div
                key={`h${index}`}
                className="flex flex-col gap-1 rounded-xl border border-dashed px-4 py-3"
              >
                <p className="text-xs text-muted-foreground">
                  {name(entry.from)} handed the work to{" "}
                  {entry.to === "human" ? "a person" : name(entry.to)}
                </p>
                {entry.brief ? (
                  <p className="text-sm">
                    {entry.brief.length > 400
                      ? `${entry.brief.slice(0, 397)}...`
                      : entry.brief}
                  </p>
                ) : null}
              </div>
            )
          )}
        </section>

        <aside className="flex flex-col gap-4">
          <BeforeLoopCard inspection={inspection} />
          <ChecksCard
            inspection={inspection}
            replied={run.events.some(
              (event) => event.kind === "ticket.replied"
            )}
          />
          <LimitsCard runs={run.agent_runs} agents={agents} />
          {replay ? null : (
            <RunAgents runs={run.agent_runs} reviews={run.reviews} />
          )}
          <ReviewCard reviews={run.reviews} />
          {run.incident ||
          run.proposals.length > 0 ||
          run.approvals.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>What it produced</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                {run.incident ? (
                  <DrawerLink
                    target={{
                      kind: "incident",
                      id: run.incident.incident_id,
                    }}
                    className="underline underline-offset-4"
                  >
                    Incident: {run.incident.report.title}
                  </DrawerLink>
                ) : null}
                {run.proposals.map((proposal) => (
                  <DrawerLink
                    key={proposal.proposal_id}
                    target={{ kind: "proposal", id: proposal.proposal_id }}
                    className="underline underline-offset-4"
                  >
                    Proposal: {proposal.proposal.title} ({proposal.status})
                  </DrawerLink>
                ))}
                {run.approvals.map((approval) => (
                  <DrawerLink
                    key={approval.approval_id}
                    target={{ kind: "approval", id: approval.approval_id }}
                    className="underline underline-offset-4"
                  >
                    Approval for {approval.action}:{" "}
                    {approval.verdict ?? "waiting"}
                  </DrawerLink>
                ))}
              </CardContent>
            </Card>
          ) : null}
          {run.ticket ? (
            <Transcript
              ticket={run.ticket}
              workItemId={item.id}
              waiting={!replay && item.status === "waiting_customer"}
            />
          ) : null}
        </aside>
      </div>

      <Collapsible>
        <Card className="gap-0 pb-0">
          <CardHeader className="border-b pb-4">
            <CollapsibleTrigger className="text-left">
              <CardTitle>Events ({run.events.length})</CardTitle>
              <CardDescription>
                Everything this run recorded, newest first. Click to show.
              </CardDescription>
            </CollapsibleTrigger>
          </CardHeader>
          <CollapsibleContent>
            <CardContent className="p-0">
              <ul className="divide-y">
                {[...run.events].reverse().map((event) => (
                  <EventRow key={event.id} event={event} />
                ))}
              </ul>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  )
}

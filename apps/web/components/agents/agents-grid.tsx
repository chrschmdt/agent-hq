"use client"

import Link from "next/link"

import { RecordingNotice } from "@/components/recording/recording-notice"
import { useRecorded } from "@/components/recording/recording-provider"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { AgentSummary } from "@/lib/api/types"
import { usd, version, words } from "@/lib/format"
import { agentsAt } from "@/lib/recording/derive"

const ROLES: Record<string, string> = {
  dispatcher: "Routes every new ticket, alert and flag to its owner.",
  support:
    "Answers customers, changes orders within policy, pauses for approval above the limit.",
  ops: "Investigates alerts and flagged patterns with read-only SQL and files incidents.",
  insights:
    "Turns incidents and patterns into proposals, and drafts help articles.",
}

function open(agent: AgentSummary): number {
  const work = agent.work
  return (
    (work.new ?? 0) +
    (work.running ?? 0) +
    (work.waiting_approval ?? 0) +
    (work.waiting_customer ?? 0)
  )
}

export function AgentsGrid({ live }: { live: AgentSummary[] | null }) {
  const recorded = useRecorded(agentsAt)
  const agents = recorded.recording ? recorded.data : live
  if (!agents) {
    return <RecordingNotice />
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {agents.map((agent) => (
        <Link key={agent.name} href={`/agents/${agent.name}`}>
          <Card className="h-full transition-colors hover:bg-muted/40">
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span className="capitalize">{agent.name}</span>
                <Badge variant="outline" className="font-mono">
                  {version(agent.version)}
                </Badge>
              </CardTitle>
              <CardDescription>{ROLES[agent.name]}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2 text-xs">
              <Badge variant="secondary">{agent.model}</Badge>
              <Badge variant="secondary">{words(agent.autonomy)}</Badge>
              <Badge variant="secondary">{agent.tools.length} tools</Badge>
              <Badge variant="secondary">answers with {agent.answer}</Badge>
              <Badge variant="secondary">
                up to {agent.max_model_calls} calls, {usd(agent.max_usd)}
              </Badge>
              <Badge variant="outline">
                {open(agent)} open, {agent.work.done ?? 0} done
              </Badge>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}

"use client"

import Link from "next/link"

import { AgentGlance } from "@/components/agents/agent-glance"
import { RecordingNotice } from "@/components/recording/recording-notice"
import { useRecorded } from "@/components/recording/recording-provider"
import { EventRow } from "@/components/feed/event-row"
import { ScorecardPanel } from "@/components/scorecards/scorecard-panel"
import { PageHeader } from "@/components/shell/page-header"
import { Badge } from "@/components/ui/badge"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { NewVersion } from "@/components/versions/new-version"
import { VersionsPanel } from "@/components/versions/versions-panel"
import { WorkStatusBadge } from "@/components/work/work-status"
import type {
  AgentDetail,
  AgentScorecards,
  AgentVersion,
  VersionConfig,
} from "@/lib/api/types"
import {
  agentAt,
  scorecardsOf,
  storeTimeOf,
  versionsOf,
} from "@/lib/recording/derive"
import { sentence, usd, version } from "@/lib/format"
import { workTitle } from "@/lib/work"

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <Collapsible className="rounded-lg border">
      <CollapsibleTrigger className="w-full px-4 py-2 text-left text-sm font-medium hover:bg-muted/40">
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t px-4 py-3">
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}

export type LiveAgent = {
  agent: AgentDetail
  versions: AgentVersion[]
  scorecards: AgentScorecards | null
  config: VersionConfig | null
  times?: Map<number, string>
}

export function AgentScreen({
  name,
  live,
}: {
  name: string
  live: LiveAgent | null
}) {
  const recorded = useRecorded((prepared, cursor) => {
    const agent = agentAt(prepared, cursor, name)
    return agent
      ? {
          agent,
          versions: versionsOf(prepared, name),
          scorecards: scorecardsOf(prepared, name),
          config: null,
          times: new Map(
            agent.recent_events.map((event) => [
              event.id,
              storeTimeOf(prepared, event),
            ])
          ),
        }
      : null
  })
  const shown = recorded.recording ? recorded.data : live
  if (!shown) {
    return <RecordingNotice />
  }
  const { agent: a, versions, scorecards, config } = shown
  const times = shown.times
  return (
    <>
      <PageHeader
        title={name.charAt(0).toUpperCase() + name.slice(1)}
        description={`Live version ${version(a.version)}${a.canary ? `, canary ${version(a.canary.version_id)} on ${a.canary.pct}% of new work` : ""}`}
      >
        <Badge variant="outline">{a.model_id}</Badge>
        {a.paused ? <Badge variant="destructive">paused</Badge> : null}
        {config ? (
          <NewVersion
            agent={name}
            live={config}
            grantedTools={a.granted_tools}
            models={a.model_choices}
          />
        ) : null}
      </PageHeader>
      <AgentGlance agent={a} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <VersionsPanel
            agent={name}
            initial={versions}
            recorded={recorded.recording}
          />
          {scorecards ? (
            <ScorecardPanel
              agent={name}
              initial={scorecards}
              recorded={recorded.recording}
            />
          ) : null}
          <Card>
            <CardHeader>
              <CardTitle>Live spec</CardTitle>
              <CardDescription>
                {sentence(a.autonomy)} autonomy, reads {a.audience} articles
                {a.customer_scoped
                  ? ", one customer per conversation"
                  : ", the whole store"}
                {a.can_flag ? ", may flag patterns" : ""}.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Section
                title={`Prompt, ${a.prompt_stable.length.toLocaleString()} characters before the context`}
              >
                <pre className="max-h-[32rem] overflow-auto font-mono text-xs whitespace-pre-wrap">
                  {a.prompt_stable}
                  {"\n\n"}
                  {a.prompt_context}
                </pre>
              </Section>
              <Section title={`Answer: ${a.answer}`}>
                <pre className="max-h-96 overflow-auto font-mono text-xs">
                  {JSON.stringify(a.answer_schema, null, 2)}
                </pre>
              </Section>
              <p className="text-xs text-muted-foreground">
                Prompt digest{" "}
                <span className="font-mono">
                  {a.prompt_digest.slice(0, 12)}
                </span>
                . Everything before the context is identical for every piece of
                work, so providers can cache it.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Tools</CardTitle>
              <CardDescription>
                {a.can_flag
                  ? "Plus flag_pattern, which the team graph runs itself."
                  : "From the one tool catalog."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {a.tool_details.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  None: one typed answer, no tools.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tool</TableHead>
                      <TableHead>Effect</TableHead>
                      <TableHead>What it does</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {a.tool_details.map((tool) => (
                      <TableRow key={tool.name}>
                        <TableCell className="font-mono text-xs">
                          {tool.name}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{tool.effect}</Badge>
                          {tool.refund_gated ? (
                            <Badge variant="outline" className="ml-1">
                              gated
                            </Badge>
                          ) : null}
                        </TableCell>
                        <TableCell className="max-w-md text-xs whitespace-normal text-muted-foreground">
                          {tool.description}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
          <Card className="gap-0 pb-0">
            <CardHeader className="border-b pb-4">
              <CardTitle>Recent activity</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {a.recent_events.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                  Nothing yet.
                </p>
              ) : (
                <ul className="divide-y">
                  {a.recent_events.map((event) => (
                    <EventRow
                      key={event.id}
                      event={event}
                      at={times?.get(event.id)}
                    />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Model by profile</CardTitle>
              <CardDescription>
                {a.version_model
                  ? `The live version names ${a.version_model}; the medium and high profiles run it, the others keep their own.`
                  : `The profile picks the model for the ${a.role} role.`}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1.5 text-sm">
              {Object.entries(a.models_by_profile).map(([profile, model]) => (
                <p key={profile} className="flex justify-between">
                  <span className="text-muted-foreground">{profile}</span>
                  <span className="font-mono text-xs">{model}</span>
                </p>
              ))}
              <p className="pt-2 text-xs text-muted-foreground">
                Limits: {a.max_model_calls} model calls, {usd(a.max_usd)} per
                work item.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Recent work</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              {a.recent_work.length === 0 ? (
                <p className="text-muted-foreground">None yet.</p>
              ) : (
                a.recent_work.map((item) => (
                  <Link
                    key={item.id}
                    href={`/runs/${item.id}`}
                    className="flex items-center justify-between gap-2"
                  >
                    <span className="truncate underline underline-offset-4">
                      {workTitle(item)}
                    </span>
                    <WorkStatusBadge status={item.status} />
                  </Link>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

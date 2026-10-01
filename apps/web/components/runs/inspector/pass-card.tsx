"use client"

import { useState } from "react"

import { useDaySpan } from "@/components/recording/recording-provider"
import { LinkedText } from "@/components/records/record-drawer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { MessageView } from "@/lib/api/types"
import { lasted, usd } from "@/lib/format"
import {
  type Answer,
  type CallStep,
  name,
  type Pass,
} from "@/lib/inspector/passes"
import { cn } from "@/lib/utils"

const CHIP = "border-transparent font-medium"
const LIVE =
  "bg-[color-mix(in_oklch,var(--map-live)_14%,transparent)] text-[var(--map-live)]"
const VERDICT: Record<
  CallStep["verdict"] | "cached",
  { label: string; className: string }
> = {
  allowed: {
    label: "allowed",
    className: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  approved: {
    label: "approved by you",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  refused: {
    label: "refused",
    className: "bg-destructive/10 text-destructive",
  },
  pending: {
    label: "not run yet",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  cached: {
    label: "read cache",
    className: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  },
}

const KIND_LABEL: Record<MessageView["kind"], string> = {
  brief: "brief",
  customer: "customer",
  check: "check",
  handoff: "handoff",
  note: "note",
  model: "model",
  earlier_reply: "earlier reply",
  tool: "tool",
}

function k(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

function since(ms: number): string {
  const s = ms / 1000
  return s >= 90
    ? `+${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
    : `+${s.toFixed(1)} s`
}

function Section({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-[6.5rem_1fr]">
      <span className="pt-0.5 text-xs text-muted-foreground">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function ContextBars({ pass, scale }: { pass: Pass; scale: number }) {
  const width = (tokens: number) => `${Math.max(0, (tokens / scale) * 100)}%`
  const share =
    pass.input > 0 ? Math.round((pass.cached / pass.input) * 100) : 0
  const { system, conversation, tools } = pass.composition
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-3.5 overflow-hidden rounded bg-muted">
        <span
          style={{
            width: width(pass.cached),
            background: "color-mix(in oklch, var(--map-live) 45%, var(--card))",
          }}
        />
        <span
          style={{
            width: width(pass.input - pass.cached),
            background: "var(--map-live)",
          }}
        />
        <span
          style={{
            width: width(Math.max(pass.output, scale / 200)),
            background: "var(--map-reply)",
          }}
        />
      </div>
      <p className="font-mono text-xs text-muted-foreground">
        {pass.input.toLocaleString("en-US")} tokens in,{" "}
        {pass.cached.toLocaleString("en-US")} from the prompt cache ({share}
        %) · {pass.output.toLocaleString("en-US")} out, reasoning included
      </p>
      <div className="flex h-1.5 overflow-hidden rounded">
        <span className="bg-foreground/25" style={{ width: width(system) }} />
        <span
          className="bg-foreground/45"
          style={{ width: width(conversation) }}
        />
        <span className="bg-foreground/65" style={{ width: width(tools) }} />
      </div>
      <p className="font-mono text-[11px] text-muted-foreground/80">
        approx. system prompt and context {k(system)} · conversation{" "}
        {k(conversation)} · tool results {k(tools)}
      </p>
    </div>
  )
}

function CallRow({ call, origin }: { call: CallStep; origin: number }) {
  const [open, setOpen] = useState(false)
  const span = useDaySpan()
  const verdict = VERDICT[call.cached ? "cached" : call.verdict]
  const args = JSON.stringify(call.args)
  return (
    <div className="flex flex-col gap-1 rounded-lg border bg-muted/30 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[13px]">{call.tool}</span>
        <Badge variant="outline" className={cn(CHIP, verdict.className)}>
          {verdict.label}
        </Badge>
        {call.verdict === "pending" ? null : (
          <span className="ml-auto font-mono text-xs text-muted-foreground tabular-nums">
            {call.seconds.toFixed(2)} s
          </span>
        )}
      </div>
      <p className="font-mono text-[11px] break-all text-muted-foreground">
        <LinkedText text={args} />
      </p>
      {call.approval ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Waited for a person: {call.approval.reason}.{" "}
          {call.approval.decidedAt !== null
            ? `Decided after ${lasted(span(origin + call.approval.requestedAt, origin + call.approval.decidedAt))}: ${call.approval.verdict ?? "decided"}.`
            : "Still waiting; the thread is saved and resumes after the decision."}
        </p>
      ) : null}
      {call.verdict === "refused" && call.reason ? (
        <p className="text-xs text-destructive">{call.reason}</p>
      ) : null}
      {!call.ok && call.verdict !== "refused" && call.error ? (
        <p className="text-xs text-destructive">{call.error}</p>
      ) : null}
      {call.summary ? (
        <p className="text-xs">
          <LinkedText text={call.summary} />
        </p>
      ) : null}
      {call.output ? (
        <>
          <button
            type="button"
            className="self-start text-xs text-muted-foreground underline underline-offset-4"
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide what came back" : "Show what came back"}
          </button>
          {open ? (
            <pre className="max-h-56 overflow-auto rounded-md bg-background p-2 font-mono text-[11px] whitespace-pre-wrap">
              <LinkedText text={call.output} />
            </pre>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

function AnswerBlock({ answer, agent }: { answer: Answer; agent: string }) {
  const fields = answer.fields
  const title = typeof fields.title === "string" ? fields.title : null
  const next = typeof fields.next === "string" ? fields.next : null
  const proposals = Array.isArray(fields.proposals) ? fields.proposals : []
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-[color-mix(in_oklch,var(--map-live)_40%,transparent)] bg-[color-mix(in_oklch,var(--map-live)_7%,transparent)] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">
          typed answer
        </span>
        {answer.status ? (
          <Badge variant="outline" className={cn(CHIP, LIVE)}>
            {answer.status.replaceAll("_", " ")}
          </Badge>
        ) : null}
        {next && next !== "none" ? (
          <Badge variant="outline">next: {name(next)}</Badge>
        ) : null}
      </div>
      {answer.reply ? (
        <p className="text-sm leading-relaxed">
          <LinkedText text={answer.reply} />
        </p>
      ) : null}
      {title ? <p className="text-sm font-medium">{title}</p> : null}
      {answer.summary && !answer.reply ? (
        <p className="text-sm leading-relaxed">
          <LinkedText text={answer.summary} />
        </p>
      ) : null}
      {proposals.length > 0 ? (
        <ul className="list-disc pl-5 text-sm">
          {proposals.map((proposal, index) => (
            <li key={index}>
              {typeof proposal === "object" &&
              proposal !== null &&
              "title" in proposal
                ? String(proposal.title)
                : "proposal"}
            </li>
          ))}
        </ul>
      ) : null}
      {answer.citations.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {answer.citations.map((citation) => (
            <span
              key={citation}
              className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px] text-[var(--map-live)]"
            >
              {citation}
            </span>
          ))}
        </div>
      ) : agent === "support" && answer.reply ? (
        <p className="text-xs text-muted-foreground">No citations.</p>
      ) : null}
    </div>
  )
}

export function PassCard({
  pass,
  origin,
  selected,
  scale,
  limit,
  onSelect,
}: {
  pass: Pass
  origin: number
  selected: boolean
  scale: number
  limit: number | null
  onSelect: () => void
}) {
  const [messages, setMessages] = useState(false)
  return (
    <div
      id={`pass-${pass.key}`}
      className={cn(
        "flex scroll-mt-20 flex-col gap-3 rounded-xl border bg-card p-4 transition-shadow",
        selected &&
          "border-[var(--map-live)] shadow-[0_0_0_3px_color-mix(in_oklch,var(--map-live)_14%,transparent)]"
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex flex-wrap items-baseline justify-between gap-2 text-left"
      >
        <span className="flex flex-wrap items-baseline gap-3">
          <span className="font-semibold">
            {name(pass.agent)}, pass {pass.n}
            {pass.repair ? " (repair)" : ""}
          </span>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {since(pass.at)} · {pass.seconds.toFixed(1)} s · {usd(pass.cost)} ·{" "}
            {pass.model}
          </span>
        </span>
        {limit ? (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {pass.n} of {limit} calls
          </span>
        ) : null}
      </button>
      <Section label="Context">
        <ContextBars pass={pass} scale={scale} />
      </Section>
      <Section label="Reasoning">
        {pass.reasoning ? (
          <div className="flex flex-col gap-1">
            <p className="text-sm leading-relaxed whitespace-pre-wrap italic">
              {pass.reasoning}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {pass.model === "fake"
                ? "The rule that chose this step: offline, rules stand in for the model."
                : "Summarized by the model, not its raw chain of thought."}
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            None returned: the model decided this step needed no thinking, or
            does not return it.
          </p>
        )}
      </Section>
      {pass.calls.length > 0 ? (
        <Section label="Tool calls">
          <div className="flex flex-col gap-2">
            {pass.calls.map((call) => (
              <CallRow key={call.id} call={call} origin={origin} />
            ))}
          </div>
        </Section>
      ) : null}
      {pass.answer ? (
        <Section label="Answer">
          <AnswerBlock answer={pass.answer} agent={pass.agent} />
        </Section>
      ) : null}
      {pass.context.length > 0 ? (
        <Section label="">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setMessages(!messages)}
          >
            {messages
              ? "Hide the messages"
              : `Show the ${pass.context.length === 1 ? "message" : `${pass.context.length} messages`} it read`}
          </Button>
        </Section>
      ) : null}
      {messages ? (
        <div className="flex flex-col gap-1.5 sm:pl-[7rem]">
          <p className="rounded-md bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
            system prompt of this version, sent first and served from the prompt
            cache when it matches
          </p>
          {pass.context.map((message, index) => (
            <div
              key={message.id ?? index}
              className="flex gap-2.5 rounded-md bg-muted/40 px-2.5 py-1.5"
            >
              <span className="w-24 shrink-0 font-mono text-[11px] text-muted-foreground">
                {KIND_LABEL[message.kind]}
                {message.tool ? ` ${message.tool}` : ""}
              </span>
              <span className="min-w-0 text-xs break-words whitespace-pre-wrap">
                <LinkedText
                  text={
                    message.kind === "model" &&
                    (message.tool_calls ?? []).length > 0
                      ? (message.tool_calls ?? [])
                          .map(
                            (call) =>
                              `${call.name}(${JSON.stringify(call.arguments)})`
                          )
                          .join("\n")
                      : message.text.length > 600
                        ? `${message.text.slice(0, 600)} [...]`
                        : message.text
                  }
                />
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

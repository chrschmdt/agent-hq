"use client"

import { useState, useTransition } from "react"
import { toast } from "sonner"

import { findSimilarTickets, searchKnowledge } from "@/app/actions"
import { BumpChart } from "@/components/retrieval/bump-chart"
import { useAdmin } from "@/components/shell/admin-context"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { SearchResult, SimilarTicket } from "@/lib/api/types"
import { moment } from "@/lib/format"
import {
  bumpLines,
  passagesById,
  STAGE_LABELS,
  STAGES,
  topIds,
} from "@/lib/retrieval"
import { cn } from "@/lib/utils"

const DEPTH = 10

function Stages({
  result,
  selected,
  onSelect,
}: {
  result: SearchResult
  selected: string | null
  onSelect: (id: string) => void
}) {
  const passages = passagesById(result)
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {STAGES.map((stage) => (
        <Card key={stage} size="sm" className="gap-2">
          <CardHeader>
            <CardTitle className="text-sm">{STAGE_LABELS[stage]}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1">
            {topIds(result, stage, DEPTH).map((id, index) => {
              const passage = passages.get(id)
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => onSelect(id)}
                  className={cn(
                    "flex gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-muted",
                    id === selected && "bg-primary/10"
                  )}
                >
                  <span className="w-4 text-muted-foreground tabular-nums">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    {passage ? `${passage.title}: ${passage.section}` : id}
                  </span>
                </button>
              )
            })}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function Similar() {
  const admin = useAdmin()
  const [text, setText] = useState("my parcel has not moved for days")
  const [tickets, setTickets] = useState<SimilarTicket[] | null>(null)
  const [pending, startTransition] = useTransition()
  const find = () =>
    startTransition(async () => {
      const result = await findSimilarTickets({ text, days: 60, intent: null })
      if (result.ok) {
        setTickets(result.data)
      } else {
        toast.error(result.error)
      }
    })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Similar tickets</CardTitle>
        <CardDescription>
          The analysts&apos; pgvector search: past tickets close in meaning,
          filtered by time in the same query.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex gap-2">
          <Input
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <Button
            onClick={find}
            disabled={!admin || pending || text.trim() === ""}
          >
            Find
          </Button>
        </div>
        {tickets?.map((ticket) => (
          <div
            key={ticket.ticket_id}
            className="flex items-start justify-between gap-3 border-t pt-2 text-sm"
          >
            <div className="min-w-0">
              <p className="truncate font-medium">{ticket.subject}</p>
              <p className="line-clamp-2 text-xs text-muted-foreground">
                {ticket.opening}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <Badge variant="outline" className="tabular-nums">
                {ticket.similarity.toFixed(3)}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {moment(ticket.created_at)}
              </span>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export function Inspector() {
  const admin = useAdmin()
  const [query, setQuery] = useState("Can I get a refund on a gift card order?")
  const [audience, setAudience] = useState<"customer" | "internal">("customer")
  const [result, setResult] = useState<SearchResult | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()
  const search = () =>
    startTransition(async () => {
      const found = await searchKnowledge({ query, audience, k: 5 })
      if (found.ok) {
        setResult(found.data)
        setSelected(found.data.passages[0]?.passage_id ?? null)
      } else {
        toast.error(found.error)
      }
    })
  const chosen =
    result && selected ? passagesById(result).get(selected) : undefined
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="flex min-w-64 flex-1 flex-col gap-1.5">
            <Label htmlFor="query">Question</Label>
            <Input
              id="query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Asked by</Label>
            <Select
              value={audience}
              onValueChange={(value) =>
                setAudience(value as "customer" | "internal")
              }
            >
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="customer">customer</SelectItem>
                <SelectItem value="internal">internal</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button
            onClick={search}
            disabled={!admin || pending || query.trim() === ""}
          >
            Search
          </Button>
          {!admin ? (
            <p className="w-full text-xs text-muted-foreground">
              A search embeds the question and reranks, which costs a little;
              sign in as the admin to run one.
            </p>
          ) : null}
        </CardContent>
      </Card>
      {result ? (
        <>
          <Stages result={result} selected={selected} onSelect={setSelected} />
          <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
            <Card>
              <CardHeader>
                <CardTitle>Rank by stage</CardTitle>
                <CardDescription>
                  The top {DEPTH} of each stage. Strong lines end in the{" "}
                  {result.passages.length} passages the agent receives; click
                  one to read it.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <BumpChart
                  lines={bumpLines(result, DEPTH)}
                  depth={DEPTH}
                  selected={selected}
                  onSelect={setSelected}
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{chosen ? chosen.title : "Passage"}</CardTitle>
                <CardDescription>
                  {chosen
                    ? `${chosen.section}, version ${chosen.version}, ${chosen.passage_id}`
                    : "Pick a passage."}
                </CardDescription>
              </CardHeader>
              <CardContent className="text-sm whitespace-pre-wrap">
                {chosen?.text}
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
      <Similar />
    </div>
  )
}

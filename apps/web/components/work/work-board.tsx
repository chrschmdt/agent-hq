"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useState } from "react"

import { RecordingNotice } from "@/components/recording/recording-notice"
import { useRecorded } from "@/components/recording/recording-provider"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Ago } from "@/components/ago"
import { api } from "@/lib/api/client"
import type { WorkItem, WorkKind } from "@/lib/api/types"
import { words } from "@/lib/format"
import { workAt } from "@/lib/recording/derive"
import { byColumn, COLUMNS, workDetail, workTitle } from "@/lib/work"

type Filter = "all" | WorkKind

async function fetchWork(filter: Filter): Promise<WorkItem[]> {
  const kind = filter === "all" ? undefined : [filter]
  const { data } = await api.GET("/api/work", {
    params: { query: { kind, limit: 300 } },
  })
  return data ?? []
}

function WorkCard({ item }: { item: WorkItem }) {
  const detail = workDetail(item)
  return (
    <Link href={`/runs/${item.id}`} className="block">
      <Card size="sm" className="gap-2 transition-colors hover:bg-muted/40">
        <CardContent className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <Badge variant="outline">{item.kind}</Badge>
            <Ago iso={item.updated_at} />
          </div>
          <span className="truncate text-sm font-medium">
            {workTitle(item)}
          </span>
          {detail ? (
            <span className="line-clamp-2 text-xs text-muted-foreground">
              {detail}
            </span>
          ) : null}
          <span className="text-xs text-muted-foreground">
            {item.owner ? words(item.owner) : "not routed yet"},{" "}
            {words(item.status)}
          </span>
        </CardContent>
      </Card>
    </Link>
  )
}

export function WorkBoard({ initial }: { initial: WorkItem[] | null }) {
  const [filter, setFilter] = useState<Filter>("all")
  const recorded = useRecorded(workAt)
  const live = useQuery({
    queryKey: ["work", filter],
    queryFn: () => fetchWork(filter),
    initialData: filter === "all" ? (initial ?? undefined) : undefined,
    enabled: !recorded.recording,
  })
  if (recorded.recording && !recorded.data) {
    return <RecordingNotice />
  }
  const items = recorded.recording
    ? (recorded.data ?? []).filter(
        (item) => filter === "all" || item.kind === filter
      )
    : (live.data ?? [])
  const columns = byColumn(items)
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        value={filter}
        onValueChange={(value) => setFilter(value as Filter)}
      >
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="ticket">Tickets</TabsTrigger>
          <TabsTrigger value="alert">Alerts</TabsTrigger>
          <TabsTrigger value="flag">Flags</TabsTrigger>
        </TabsList>
      </Tabs>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {COLUMNS.map((column) => (
          <Card key={column.key} className="gap-3 bg-muted/30">
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-sm">
                {column.title}
                <span className="text-muted-foreground tabular-nums">
                  {columns[column.key].length}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex max-h-[70vh] flex-col gap-2 overflow-y-auto">
              {columns[column.key].length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  Nothing here.
                </p>
              ) : (
                columns[column.key].map((item) => (
                  <WorkCard key={item.id} item={item} />
                ))
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

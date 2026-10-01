"use client"

import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import { clearActivity } from "@/app/actions"
import { useLive } from "@/components/live/live-provider"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import type { ActivityReport } from "@/lib/api/types"

const GOES = [
  "Every event in the feed, and every work item with its run",
  "Approvals, incidents, proposals and drafts",
  "QA reviews and labels, and eval runs",
  "Today's spend, the kill switches and the model breakers",
  "Simulated days, which you can no longer record once cleared",
]

const STAYS = [
  "The store, its customers, orders and history",
  "Recorded days, published or not",
  "The model profile the team plays on",
]

function done(report: ActivityReport): string {
  const rows = Object.values(report.records).reduce((sum, n) => sum + n, 0)
  const knowledge =
    report.passages === null
      ? " The knowledge base has no saved copy yet: run `ahq kb ingest` once to make one."
      : ` The knowledge base is back to ${report.passages} passages.`
  const versions = report.versions ? " Every agent is back on version 1." : ""
  return `Cleared ${rows.toLocaleString("en-US")} records.${knowledge}${versions}`
}

export function DataAdmin() {
  const router = useRouter()
  const { status } = useLive()
  const [open, setOpen] = useState(false)
  const [versions, setVersions] = useState(true)
  const [pending, startTransition] = useTransition()
  const busy = Boolean(status && (status.simulating || status.active_work > 0))

  const clear = () =>
    startTransition(async () => {
      const result = await clearActivity(versions)
      if (!result.ok) {
        toast.error(result.error)
        return
      }
      setOpen(false)
      toast.success(done(result.data))
      router.refresh()
    })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Clear the activity</CardTitle>
        <CardDescription>
          Start the next day from a clean slate, before you record one for
          visitors. This does what{" "}
          <code className="font-mono text-xs">ahq db clear-activity</code> does
          from the command line.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">What goes</span>
            <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-muted-foreground">
              {GOES.map((line) => (
                <li key={line}>{line}</li>
              ))}
              <li>
                Articles published since the knowledge base was last ingested,
                and drafts waiting
              </li>
            </ul>
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">What stays</span>
            <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-muted-foreground">
              {STAYS.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <Switch
            id="versions"
            checked={versions}
            onCheckedChange={setVersions}
          />
          <div className="flex flex-col gap-0.5">
            <Label htmlFor="versions">Also reset the agent versions</Label>
            <span className="text-xs text-muted-foreground">
              Every agent goes back to version 1 from its code; drafts, canaries
              and later versions go.
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger
              render={<Button variant="destructive" disabled={busy} />}
            >
              Clear the activity
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Clear everything the team did?</DialogTitle>
                <DialogDescription>
                  This cannot be undone.{" "}
                  {versions
                    ? "Every agent also goes back to version 1."
                    : "The agent versions stay."}{" "}
                  Recorded days stay.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={clear}
                  disabled={pending}
                >
                  Clear it all
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          {busy ? (
            <span className="text-sm text-muted-foreground">
              A day is running or work is in flight. Stop the day and let the
              work finish first.
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

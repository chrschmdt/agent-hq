"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import { createVersion } from "@/app/actions"
import { useCanAct } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import type { VersionConfig } from "@/lib/api/types"
import { version } from "@/lib/format"

const PROFILE_MODEL = "profile"

export function NewVersion({
  agent,
  live,
  grantedTools,
  models,
}: {
  agent: string
  live: VersionConfig
  grantedTools: string[]
  models: string[]
}) {
  const admin = useCanAct()
  const router = useRouter()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [model, setModel] = useState(live.model ?? PROFILE_MODEL)
  const [calls, setCalls] = useState(String(live.max_model_calls))
  const [spend, setSpend] = useState(String(live.max_usd))
  const [tools, setTools] = useState(new Set(live.tools))
  const [stable, setStable] = useState(live.prompt_stable)
  const [context, setContext] = useState(live.prompt_context)
  const [note, setNote] = useState("")
  const [pending, startTransition] = useTransition()
  if (!admin) {
    return null
  }
  const choices = [
    { value: PROFILE_MODEL, label: "The profile's model for the role" },
    ...models.map((key) => ({ value: key, label: key })),
  ]
  const toggle = (tool: string, on: boolean) =>
    setTools((current) => {
      const next = new Set(current)
      if (on) {
        next.add(tool)
      } else {
        next.delete(tool)
      }
      return next
    })
  const submit = () =>
    startTransition(async () => {
      const config: VersionConfig = {
        model: model === PROFILE_MODEL ? null : model,
        prompt_stable: stable,
        prompt_context: context,
        tools: grantedTools.filter((tool) => tools.has(tool)),
        max_model_calls: Math.max(1, Math.round(Number(calls) || 1)),
        max_usd: Math.max(0.001, Number(spend) || live.max_usd),
      }
      const result = await createVersion(agent, config, note.trim())
      if (!result.ok) {
        toast.error(result.error)
        return
      }
      toast.success(`${version(result.data.version_id)} is drafted.`)
      setOpen(false)
      await client.invalidateQueries({ queryKey: ["versions"] })
      router.push(`/agents/${agent}/versions/${result.data.version_id}`)
    })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>New version</DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Draft a new version of {agent}</DialogTitle>
          <DialogDescription>
            Starts from the live version. A version may change its model, limits
            and prompt, and drop tools; granting a tool is a change to the code.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <Label>Model</Label>
            <Select
              value={model}
              onValueChange={(value) => setModel(String(value))}
              items={choices}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {choices.map((choice) => (
                  <SelectItem key={choice.value} value={choice.value}>
                    {choice.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="calls">Model calls per turn</Label>
            <Input
              id="calls"
              inputMode="numeric"
              value={calls}
              onChange={(event) => setCalls(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="spend">Dollars per work item</Label>
            <Input
              id="spend"
              inputMode="decimal"
              value={spend}
              onChange={(event) => setSpend(event.target.value)}
            />
          </div>
        </div>
        <p className="-mt-3 text-xs text-muted-foreground">
          Only the medium and high profiles run the model a version names; the
          others keep their own.
        </p>
        {grantedTools.length > 0 ? (
          <div className="flex flex-col gap-2">
            <Label>Tools</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {grantedTools.map((tool) => (
                <label
                  key={tool}
                  className="flex items-center gap-2 font-mono text-xs"
                >
                  <Switch
                    checked={tools.has(tool)}
                    onCheckedChange={(on) => toggle(tool, on)}
                  />
                  {tool}
                </label>
              ))}
            </div>
          </div>
        ) : null}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="stable">
            Prompt, the part every piece of work shares
          </Label>
          <Textarea
            id="stable"
            value={stable}
            onChange={(event) => setStable(event.target.value)}
            className="h-72 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="context">
            Context, filled in for each piece of work
          </Label>
          <Textarea
            id="context"
            value={context}
            onChange={(event) => setContext(event.target.value)}
            className="h-28 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="note">What changed and why</Label>
          <Input
            id="note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={pending || note.trim().length < 3}>
            Save as a draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

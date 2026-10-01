"use client"

import { useState, useTransition } from "react"

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
import { Switch } from "@/components/ui/switch"

export type ActionValues = { reason: string; pct: number; flag: boolean }

export function ActionDialog({
  label,
  title,
  description,
  confirm,
  reason = false,
  pct,
  flag,
  destructive = false,
  onConfirm,
}: {
  label: string
  title: string
  description: string
  confirm: string
  reason?: boolean
  pct?: number
  flag?: string
  destructive?: boolean
  onConfirm: (values: ActionValues) => Promise<boolean>
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const [share, setShare] = useState(String(pct ?? 20))
  const [checked, setChecked] = useState(false)
  const [pending, startTransition] = useTransition()
  const ready = !reason || text.trim().length >= 3
  const submit = () =>
    startTransition(async () => {
      const done = await onConfirm({
        reason: text.trim(),
        pct: Math.min(100, Math.max(1, Number(share) || 20)),
        flag: checked,
      })
      if (done) {
        setOpen(false)
        setText("")
      }
    })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant={destructive ? "outline" : "secondary"} size="sm" />
        }
      >
        {label}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          {pct !== undefined ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pct">Share of new work, in percent</Label>
              <Input
                id="pct"
                inputMode="numeric"
                value={share}
                onChange={(event) => setShare(event.target.value)}
              />
            </div>
          ) : null}
          {reason ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="reason">Reason, for the timeline</Label>
              <Input
                id="reason"
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
            </div>
          ) : null}
          {flag ? (
            <div className="flex items-center gap-2">
              <Switch
                id="flag"
                checked={checked}
                onCheckedChange={setChecked}
              />
              <Label htmlFor="flag">{flag}</Label>
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={submit}
            disabled={pending || !ready}
          >
            {confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

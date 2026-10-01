"use client"

import { useQueryClient } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { useState, useTransition } from "react"
import { toast } from "sonner"

import { decideApproval } from "@/app/actions"
import { useSource } from "@/components/recording/recording-provider"
import { useCanAct } from "@/components/shell/admin-context"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import type { Approval, ApprovalDecision, ToolInfo } from "@/lib/api/types"
import { changed, fieldsOf, toArguments, toValues } from "@/lib/schema-form"

export function DecisionPanel({
  approval,
  tool,
}: {
  approval: Approval
  tool: ToolInfo | null
}) {
  const admin = useCanAct()
  const recording = useSource().mode === "recording"
  const router = useRouter()
  const client = useQueryClient()
  const original = approval.request.arguments as Record<string, unknown>
  const fields = tool
    ? fieldsOf(tool.parameters as Record<string, unknown>)
    : []
  const [values, setValues] = useState(() => toValues(fields, original))
  const [asJson, setAsJson] = useState(fields.length === 0)
  const [json, setJson] = useState(() => JSON.stringify(original, null, 2))
  const [note, setNote] = useState("")
  const [pending, startTransition] = useTransition()
  const open = approval.status === "pending"
  const enabled = admin && open && !pending

  const current = ():
    | { ok: true; args: Record<string, unknown> }
    | { ok: false; error: string } => {
    if (!asJson) {
      return toArguments(fields, values)
    }
    try {
      return { ok: true, args: JSON.parse(json) as Record<string, unknown> }
    } catch {
      return { ok: false, error: "The arguments are not valid JSON." }
    }
  }

  const decide = (verdict: ApprovalDecision["verdict"]) => {
    const parsed = current()
    if (!parsed.ok) {
      toast.error(parsed.error)
      return
    }
    const edited = verdict !== "reject" && changed(original, parsed.args)
    const decision: ApprovalDecision = {
      verdict: edited ? "edit" : verdict,
      arguments: edited ? parsed.args : null,
      note: note.trim() || null,
    }
    startTransition(async () => {
      const result = await decideApproval(approval.id, decision)
      if (result.ok) {
        toast.success(
          `Decision recorded: ${decision.verdict}. The agent carries on.`
        )
        router.refresh()
        await client.invalidateQueries({ queryKey: ["approvals"] })
      } else {
        toast.error(result.error)
      }
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Arguments</CardTitle>
        <CardDescription>
          {open
            ? admin
              ? "Change anything before approving; the agent runs exactly what you approve."
              : recording
                ? "Waiting for a person. Play on to see what they decided."
                : "Sign in as the admin to decide."
            : `Decided: ${approval.decision?.verdict ?? approval.status}${approval.decision?.note ? `, "${approval.decision.note}"` : ""}.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Switch
            id="as-json"
            checked={asJson}
            onCheckedChange={setAsJson}
            disabled={fields.length === 0}
          />
          <Label htmlFor="as-json">Edit as JSON</Label>
        </div>
        {asJson ? (
          <Textarea
            value={json}
            onChange={(event) => setJson(event.target.value)}
            disabled={!enabled}
            className="min-h-48 font-mono text-xs"
          />
        ) : (
          fields.map((field) => (
            <div key={field.name} className="flex flex-col gap-1.5">
              <Label htmlFor={field.name}>
                {field.label}
                {field.required ? "" : " (optional)"}
              </Label>
              {field.kind === "text" || field.kind === "number" ? (
                <Input
                  id={field.name}
                  value={values[field.name]}
                  inputMode={field.kind === "number" ? "decimal" : undefined}
                  onChange={(event) =>
                    setValues({ ...values, [field.name]: event.target.value })
                  }
                  disabled={!enabled}
                />
              ) : (
                <Textarea
                  id={field.name}
                  value={values[field.name]}
                  onChange={(event) =>
                    setValues({ ...values, [field.name]: event.target.value })
                  }
                  disabled={!enabled}
                  className="font-mono text-xs"
                />
              )}
              {field.description ? (
                <p className="text-xs text-muted-foreground">
                  {field.description}
                  {field.kind === "list" ? " One per line." : ""}
                </p>
              ) : null}
            </div>
          ))
        )}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="note">Note to the agent</Label>
          <Textarea
            id="note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Required to reject; the agent reads it and tells the customer why."
            disabled={!enabled}
          />
        </div>
      </CardContent>
      <CardFooter className="flex flex-wrap justify-end gap-2">
        <Button
          variant="destructive"
          onClick={() => decide("reject")}
          disabled={!enabled || note.trim() === ""}
        >
          Reject
        </Button>
        <Button onClick={() => decide("approve")} disabled={!enabled}>
          Approve
        </Button>
      </CardFooter>
    </Card>
  )
}

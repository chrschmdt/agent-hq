"use client"

import Link from "next/link"

import { useDaySpan } from "@/components/recording/recording-provider"
import { DrawerLink } from "@/components/shell/drawer-context"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { ChainStep, ChainTone } from "@/lib/inspector/chain"

const DOT: Record<ChainTone, string> = {
  alert: "var(--map-amber)",
  agent: "var(--map-live)",
  you: "var(--map-amber)",
  published: "var(--map-violet)",
  cited: "var(--map-live)",
}

function since(ms: number): string {
  const s = Math.max(0, ms / 1000)
  if (s < 60) {
    return `+${s.toFixed(0)} s`
  }
  if (s < 3600) {
    return `+${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
  }
  return `+${Math.floor(s / 3600)}h ${Math.round((s % 3600) / 60)}m`
}

export function IncidentChain({
  steps,
  origin,
}: {
  steps: ChainStep[]
  origin: number
}) {
  const span = useDaySpan()
  if (steps.length === 0) {
    return null
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>How it unfolded</CardTitle>
        <CardDescription>
          From the alert to the replies that used what the team published, each
          step as its events recorded it. Times count from the alert.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="relative flex flex-col gap-5 border-l border-dashed pl-6">
          {steps.map((step, index) => (
            <li key={index} className="relative flex flex-col gap-1">
              <span
                className="absolute top-1 -left-[31px] size-3 rounded-full ring-4 ring-card"
                style={{ background: DOT[step.tone] }}
              />
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  {since(span(origin, origin + step.at))}
                </span>
                <span className="text-sm font-medium">{step.title}</span>
              </div>
              {step.detail ? (
                <p className="text-sm text-muted-foreground">{step.detail}</p>
              ) : null}
              {step.links.length > 0 ? (
                <div className="flex flex-wrap gap-3 text-xs">
                  {step.links.map((link) =>
                    "target" in link ? (
                      <DrawerLink
                        key={`${link.target.kind}:${link.target.id}`}
                        target={link.target}
                        className="underline underline-offset-4"
                      >
                        {link.label}
                      </DrawerLink>
                    ) : (
                      <Link
                        key={link.href}
                        href={link.href}
                        className="underline underline-offset-4"
                      >
                        {link.label}
                      </Link>
                    )
                  )}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

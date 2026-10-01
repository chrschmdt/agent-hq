"use client"

import { usePathname } from "next/navigation"
import { useCallback, useMemo, useRef, useState } from "react"

import { ApprovalPanel } from "@/components/approvals/approval-screen"
import { RecordPanel } from "@/components/records/record-drawer"
import { DrawerContext } from "@/components/shell/drawer-context"
import { IncidentPanel } from "@/components/team/incident-screen"
import { ProposalPanel } from "@/components/team/proposal-screen"
import { Sheet, SheetContent } from "@/components/ui/sheet"
import { type DrawerTarget, isDetail } from "@/lib/drawer"
import { cn } from "@/lib/utils"

export function DrawerProvider({ children }: { children: React.ReactNode }) {
  const [stack, setStack] = useState<DrawerTarget[]>([])
  const popup = useRef<HTMLDivElement>(null)
  const pathname = usePathname()
  const [openedOn, setOpenedOn] = useState(pathname)
  if (pathname !== openedOn) {
    setOpenedOn(pathname)
    setStack([])
  }
  const open = useCallback(
    (target: DrawerTarget) =>
      setStack((current) => {
        const top = current.at(-1)
        return top && top.kind === target.kind && top.id === target.id
          ? current
          : [...current, target]
      }),
    []
  )
  const back = useMemo(
    () =>
      stack.length > 1
        ? () => setStack((current) => current.slice(0, -1))
        : null,
    [stack.length]
  )
  const top = stack.at(-1) ?? null
  const wide = stack.some(isDetail)
  return (
    <DrawerContext value={{ open, back }}>
      {children}
      <Sheet
        open={top !== null}
        onOpenChange={(opened) => {
          if (!opened) {
            setStack([])
          }
        }}
      >
        <SheetContent
          ref={popup}
          initialFocus={popup}
          side="right"
          className={cn(
            "gap-0 data-[side=right]:w-full",
            wide
              ? "data-[side=right]:sm:max-w-2xl data-[side=right]:lg:max-w-4xl"
              : "data-[side=right]:sm:max-w-md"
          )}
          onClickCapture={(event) => {
            const link = (event.target as Element).closest("a[href]")
            const newTab =
              event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
            if (link && !link.hasAttribute("data-drawer-link") && !newTab) {
              setStack([])
            }
          }}
        >
          {top ? (
            <Panel key={`${top.kind}:${top.id}:${stack.length}`} target={top} />
          ) : null}
        </SheetContent>
      </Sheet>
    </DrawerContext>
  )
}

function Panel({ target }: { target: DrawerTarget }) {
  switch (target.kind) {
    case "approval":
      return <ApprovalPanel approvalId={target.id} />
    case "incident":
      return <IncidentPanel incidentId={target.id} />
    case "proposal":
      return <ProposalPanel proposalId={target.id} />
    default:
      return <RecordPanel target={target} />
  }
}

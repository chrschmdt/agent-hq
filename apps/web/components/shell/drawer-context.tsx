"use client"

import { ArrowLeft01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { usePathname, useRouter } from "next/navigation"
import { createContext, useContext, useEffect } from "react"

import { RecordingNotice } from "@/components/recording/recording-notice"
import { useSource } from "@/components/recording/recording-provider"
import { Button } from "@/components/ui/button"
import {
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { type DetailRef, detailHref, type DrawerTarget } from "@/lib/drawer"
import { cn } from "@/lib/utils"

type Drawer = {
  open: (target: DrawerTarget) => void
  back: (() => void) | null
}

export const DrawerContext = createContext<Drawer>({
  open: () => undefined,
  back: null,
})

export function useDrawer(): Drawer {
  return useContext(DrawerContext)
}

export function DrawerLink({
  target,
  className,
  children,
}: {
  target: DetailRef
  className?: string
  children: React.ReactNode
}) {
  const { open } = useDrawer()
  return (
    <a
      href={detailHref(target)}
      data-drawer-link=""
      className={className}
      onClick={(event) => {
        if (
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return
        }
        event.preventDefault()
        open(target)
      }}
    >
      {children}
    </a>
  )
}

export function OpenInDrawer({ target }: { target: DrawerTarget }) {
  const { open } = useDrawer()
  const router = useRouter()
  const pathname = usePathname()
  const { kind, id } = target
  useEffect(() => {
    open({ kind, id } as DrawerTarget)
    router.replace(pathname, { scroll: false })
  }, [kind, id, open, router, pathname])
  return null
}

export function DrawerHeader({
  title,
  description,
  hideDescription = false,
  children,
}: {
  title: React.ReactNode
  description: string
  hideDescription?: boolean
  children?: React.ReactNode
}) {
  const { back } = useDrawer()
  return (
    <SheetHeader className="gap-1 border-b pr-14">
      {back ? (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 w-fit gap-1 text-muted-foreground"
          onClick={back}
        >
          <HugeiconsIcon icon={ArrowLeft01Icon} className="size-4" />
          Back
        </Button>
      ) : null}
      <SheetTitle className="flex items-baseline gap-2 text-lg text-balance">
        {title}
      </SheetTitle>
      <SheetDescription className={cn(hideDescription && "sr-only")}>
        {description}
      </SheetDescription>
      {children ? (
        <div className="mt-1 flex flex-wrap items-center gap-2">{children}</div>
      ) : null}
    </SheetHeader>
  )
}

export function DrawerBody({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "@container flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4 text-sm sm:p-6",
        className
      )}
    >
      {children}
    </div>
  )
}

export function DrawerPending({
  title,
  id,
  notYet,
  live,
}: {
  title: string
  id: string
  notYet: string
  live: { isPending: boolean; isError: boolean }
}) {
  const { mode, prepared } = useSource()
  return (
    <>
      <DrawerHeader title={title} description={id} />
      <DrawerBody>
        {mode === "recording" && !prepared ? (
          <RecordingNotice />
        ) : (
          <p className="text-muted-foreground">
            {mode === "recording"
              ? notYet
              : live.isError
                ? "Could not load it."
                : live.isPending
                  ? "Loading."
                  : "Not found."}
          </p>
        )}
      </DrawerBody>
    </>
  )
}

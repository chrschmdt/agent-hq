"use client"

import {
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
} from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { railTip } from "@/components/shell/rail-tip"
import {
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export function SidebarToggle() {
  const { state, toggleSidebar } = useSidebar()
  const label = state === "expanded" ? "Collapse sidebar" : "Expand sidebar"
  const icon = state === "expanded" ? PanelLeftOpenIcon : PanelLeftCloseIcon
  return (
    <SidebarMenuItem className="hidden md:block">
      <SidebarMenuButton
        onClick={toggleSidebar}
        tooltip={railTip(label)}
        aria-label={label}
        aria-expanded={state === "expanded"}
        className="text-muted-foreground"
      >
        <HugeiconsIcon icon={icon} />
        <span>Collapse</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

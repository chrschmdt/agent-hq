"use client"

import {
  AiBrain01Icon,
  Alert02Icon,
  CheckmarkBadge01Icon,
  DashboardSquare01Icon,
  Database01Icon,
  Idea01Icon,
  LabelIcon,
  Money03Icon,
  PlayCircleIcon,
  Search01Icon,
  Target02Icon,
  Task01Icon,
  TestTube01Icon,
  UserGroupIcon,
  VideoReplayIcon,
} from "@hugeicons/core-free-icons"
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { ModeSwitch } from "@/components/recording/mode-switch"
import { useAdmin } from "@/components/shell/admin-context"
import { railTip } from "@/components/shell/rail-tip"
import { SidebarToggle } from "@/components/shell/sidebar-toggle"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { useStatus } from "@/hooks/use-status"

type Item = { href: string; label: string; icon: IconSvgElement }

const WATCH: Item[] = [
  { href: "/overview", label: "Overview", icon: DashboardSquare01Icon },
  { href: "/work", label: "Work", icon: Task01Icon },
  { href: "/agents", label: "Agents", icon: UserGroupIcon },
]
const DECIDE: Item[] = [
  { href: "/approvals", label: "Approvals", icon: CheckmarkBadge01Icon },
  { href: "/incidents", label: "Incidents", icon: Alert02Icon },
  { href: "/proposals", label: "Proposals", icon: Idea01Icon },
]
const MEASURE: Item[] = [
  { href: "/evals", label: "Evals", icon: TestTube01Icon },
  { href: "/quality", label: "Quality", icon: Target02Icon },
]
const ADMIN: Item[] = [
  { href: "/admin/models", label: "Models", icon: AiBrain01Icon },
  { href: "/admin/spend", label: "Spend and limits", icon: Money03Icon },
  { href: "/admin/recordings", label: "Recordings", icon: VideoReplayIcon },
  { href: "/admin/simulator", label: "Simulator", icon: PlayCircleIcon },
  { href: "/admin/retrieval", label: "Retrieval", icon: Search01Icon },
  { href: "/admin/labeling", label: "Labeling", icon: LabelIcon },
  { href: "/admin/data", label: "Data", icon: Database01Icon },
]

function Mark() {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden
      className="size-7 shrink-0"
      fill="none"
      stroke="#14b8a6"
      strokeWidth="4"
      strokeLinecap="round"
    >
      <circle cx="32" cy="15.1" r="5.2" />
      <path d="M37.15 15.79A19.5 19.5 0 0 1 51.31 31.88" />
      <circle cx="48.89" cy="44.35" r="5.2" />
      <path d="M45.71 48.47A19.5 19.5 0 0 1 24.7 52.68" />
      <circle cx="15.11" cy="44.35" r="5.2" />
      <path d="M13.14 39.54A19.5 19.5 0 0 1 19.99 19.24" />
    </svg>
  )
}

function Group({
  label,
  items,
  badges,
}: {
  label: string
  items: Item[]
  badges?: Record<string, number>
}) {
  const pathname = usePathname()
  return (
    <SidebarGroup>
      <SidebarGroupLabel>{label}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => (
            <SidebarMenuItem key={item.href}>
              <SidebarMenuButton
                isActive={pathname.startsWith(item.href)}
                tooltip={railTip(item.label)}
                render={<Link href={item.href} />}
              >
                <HugeiconsIcon icon={item.icon} />
                <span>{item.label}</span>
              </SidebarMenuButton>
              {badges?.[item.href] ? (
                <SidebarMenuBadge>{badges[item.href]}</SidebarMenuBadge>
              ) : null}
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

export function AppSidebar({ footer }: { footer: React.ReactNode }) {
  const status = useStatus()
  const admin = useAdmin()
  const badges = { "/approvals": status?.pending_approvals ?? 0 }
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Link
          href="/overview"
          className="flex items-center gap-2 px-0.5 py-1.5 font-medium"
        >
          <Mark />
          <span className="sidebar-fade min-w-0 overflow-hidden whitespace-nowrap group-data-[collapsible=icon]:opacity-0">
            AHQ <span className="text-muted-foreground">Control room</span>
          </span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <Group label="Watch" items={WATCH} />
        <Group label="Decide" items={DECIDE} badges={badges} />
        <Group label="Measure" items={MEASURE} />
        {admin ? <Group label="Admin" items={ADMIN} /> : null}
      </SidebarContent>
      <SidebarFooter>
        <ModeSwitch />
        <SidebarMenu>
          {footer}
          <SidebarToggle />
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}

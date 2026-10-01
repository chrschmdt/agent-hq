import { Login01Icon, Logout01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { signInAction, signOutAction } from "@/app/actions"
import { railTip } from "@/components/shell/rail-tip"
import {
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

export function AdminMenu({
  login,
  provider,
}: {
  login: string | null
  provider: "github" | "local" | null
}) {
  if (login !== null) {
    return (
      <SidebarMenuItem>
        <form action={signOutAction}>
          <SidebarMenuButton
            type="submit"
            aria-label="Sign out"
            tooltip={railTip(`Sign out ${login}`)}
            className="text-muted-foreground"
          >
            <HugeiconsIcon icon={Logout01Icon} />
            <span>Sign out</span>
          </SidebarMenuButton>
        </form>
        <SidebarMenuBadge className="top-1.5 max-w-28 truncate font-normal text-muted-foreground">
          {login}
        </SidebarMenuBadge>
      </SidebarMenuItem>
    )
  }
  const label =
    provider === "local" ? "Sign in as local admin" : "Admin sign in"
  return (
    <SidebarMenuItem>
      <form action={signInAction}>
        <SidebarMenuButton
          type="submit"
          aria-label={label}
          disabled={provider === null}
          tooltip={railTip(label)}
          className="text-muted-foreground"
        >
          <HugeiconsIcon icon={Login01Icon} />
          <span>{label}</span>
        </SidebarMenuButton>
      </form>
    </SidebarMenuItem>
  )
}

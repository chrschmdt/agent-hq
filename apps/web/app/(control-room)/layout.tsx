import { cookies } from "next/headers"

import { currentSession, signInProvider } from "@/auth"
import { LiveProvider } from "@/components/live/live-provider"
import { PlayerDock } from "@/components/recording/player-dock"
import { RecordingProvider } from "@/components/recording/recording-provider"
import { AdminProvider } from "@/components/shell/admin-context"
import { AdminMenu } from "@/components/shell/admin-menu"
import { AppSidebar } from "@/components/shell/app-sidebar"
import { DrawerProvider } from "@/components/shell/drawer-host"
import { SimDock } from "@/components/sim/sim-dock"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { CACHED, cachedRead } from "@/lib/api/cached"
import { serverApi } from "@/lib/api/server"
import type { RecordingInfo } from "@/lib/api/types"

export const dynamic = "force-dynamic"

async function published(): Promise<RecordingInfo[]> {
  try {
    return await cachedRead(CACHED.recordings, "published", 600, async () => {
      const { data } = await serverApi.GET("/api/recordings")
      return data
    })
  } catch {
    return []
  }
}

export default async function ControlRoomLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const session = await currentSession()
  const admin = session !== null
  const recordings = await published()
  const sidebarOpen = (await cookies()).get("sidebar_state")?.value === "true"
  return (
    <AdminProvider admin={admin}>
      <LiveProvider enabled={admin}>
        <RecordingProvider admin={admin} recordings={recordings}>
          <DrawerProvider>
            <SidebarProvider defaultOpen={sidebarOpen}>
              <AppSidebar
                footer={
                  <AdminMenu
                    login={session?.login ?? null}
                    provider={signInProvider}
                  />
                }
              />
              <SidebarInset className="min-w-0">
                <div className="mx-auto flex w-full max-w-7xl min-w-0 flex-1 flex-col gap-6 px-4 py-6 md:px-8">
                  {children}
                </div>
                <PlayerDock />
                <SimDock />
              </SidebarInset>
              <Toaster />
            </SidebarProvider>
          </DrawerProvider>
        </RecordingProvider>
      </LiveProvider>
    </AdminProvider>
  )
}

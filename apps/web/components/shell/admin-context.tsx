"use client"

import { createContext, useContext } from "react"

import { useSource } from "@/components/recording/recording-provider"

const AdminContext = createContext(false)

export function AdminProvider({
  admin,
  children,
}: {
  admin: boolean
  children: React.ReactNode
}) {
  return <AdminContext value={admin}>{children}</AdminContext>
}

export function useAdmin(): boolean {
  return useContext(AdminContext)
}

export function useCanAct(): boolean {
  const admin = useAdmin()
  const { mode } = useSource()
  return admin && mode === "live"
}

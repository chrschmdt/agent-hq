import { notFound } from "next/navigation"

import { isAdmin } from "@/auth"

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  if (!(await isAdmin())) {
    notFound()
  }
  return <>{children}</>
}

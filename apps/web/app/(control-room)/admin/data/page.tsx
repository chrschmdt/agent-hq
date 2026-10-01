import type { Metadata } from "next"

import { DataAdmin } from "@/components/admin/data-admin"
import { PageHeader } from "@/components/shell/page-header"

export const metadata: Metadata = { title: "Data" }

export default function DataPage() {
  return (
    <>
      <PageHeader
        title="Data"
        description="What the team did, and clearing it before a clean day."
      />
      <DataAdmin />
    </>
  )
}

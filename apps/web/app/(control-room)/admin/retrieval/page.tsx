import type { Metadata } from "next"

import { Inspector } from "@/components/retrieval/inspector"
import { PageHeader } from "@/components/shell/page-header"

export const metadata: Metadata = { title: "Retrieval" }

export default function RetrievalPage() {
  return (
    <>
      <PageHeader
        title="Retrieval"
        description="Dense, BM25, fused and reranked: every stage of a knowledge base search, side by side."
      />
      <Inspector />
    </>
  )
}

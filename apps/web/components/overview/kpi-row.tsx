"use client"

import { KpiCard } from "@/components/charts/kpi-card"
import { useRecorded } from "@/components/recording/recording-provider"
import type { KpiPoint } from "@/lib/api/types"
import { KPIS } from "@/lib/kpis"
import { kpisOf } from "@/lib/recording/derive"

export function KpiRow({ initial }: { initial: KpiPoint[][] | null }) {
  const recorded = useRecorded((prepared) =>
    KPIS.map(({ metric }) => kpisOf(prepared, metric))
  )
  const points = recorded.recording ? recorded.data : initial
  if (!points) {
    return null
  }
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {KPIS.map((kpi, index) => (
        <KpiCard
          key={kpi.metric}
          label={kpi.label}
          unit={kpi.unit}
          points={points[index] ?? []}
          higherIsBetter={kpi.higherIsBetter}
        />
      ))}
    </section>
  )
}

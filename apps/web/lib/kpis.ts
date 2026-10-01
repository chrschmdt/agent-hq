import type { KpiUnit } from "@/components/charts/kpi-card"

export const KPIS: {
  metric: "orders" | "late_delivery_rate" | "tickets" | "csat"
  label: string
  unit: KpiUnit
  higherIsBetter: boolean
}[] = [
  {
    metric: "orders",
    label: "Orders per day",
    unit: "count",
    higherIsBetter: true,
  },
  {
    metric: "late_delivery_rate",
    label: "Late deliveries",
    unit: "rate",
    higherIsBetter: false,
  },
  {
    metric: "tickets",
    label: "Tickets per day",
    unit: "count",
    higherIsBetter: false,
  },
  {
    metric: "csat",
    label: "Customer satisfaction",
    unit: "score",
    higherIsBetter: true,
  },
]

import type { RecordRef } from "@/lib/records/ids"

export type DetailKind = "approval" | "incident" | "proposal"
export type DetailRef = { kind: DetailKind; id: string }

export type DrawerTarget = RecordRef | DetailRef

export const DETAIL_PAGES: Record<DetailKind, string> = {
  approval: "/approvals",
  incident: "/incidents",
  proposal: "/proposals",
}

export function isDetail(target: DrawerTarget): target is DetailRef {
  return target.kind in DETAIL_PAGES
}

export function detailHref(target: DetailRef): string {
  return `${DETAIL_PAGES[target.kind]}?open=${encodeURIComponent(target.id)}`
}

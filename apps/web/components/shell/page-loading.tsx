import { Skeleton } from "@/components/ui/skeleton"

export function PageLoading() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true">
      <span className="sr-only">Loading</span>
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-48 rounded-lg" />
        <Skeleton className="h-4 w-full max-w-md rounded-md" />
      </div>
      <Skeleton className="h-[26rem] w-full rounded-4xl" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40 rounded-4xl" />
        <Skeleton className="h-40 rounded-4xl" />
      </div>
    </div>
  )
}

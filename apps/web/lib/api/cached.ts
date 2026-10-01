import "server-only"

import { revalidateTag, unstable_cache } from "next/cache"

export const CACHED = {
  recordings: "recordings",
  evals: "evals",
  calibration: "calibration",
  graph: "graph",
  versions: "versions",
} as const

type Tag = (typeof CACHED)[keyof typeof CACHED]

const BUILD = process.env.VERCEL_GIT_COMMIT_SHA ?? "local"

export async function cachedRead<T>(
  tag: Tag,
  key: string,
  seconds: number,
  load: () => Promise<T | undefined>
): Promise<T> {
  const loaded = async () => {
    const value = await load()
    if (value === undefined) {
      throw new Error(`could not load ${key}`)
    }
    return value
  }
  if (process.env.NODE_ENV === "development") {
    return loaded()
  }
  return unstable_cache(loaded, [BUILD, tag, key], {
    tags: [tag],
    revalidate: seconds,
  })()
}

export function forget(...tags: Tag[]): void {
  for (const tag of tags) {
    revalidateTag(tag, { expire: 0 })
  }
}

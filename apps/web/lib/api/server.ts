import "server-only"

import createClient from "openapi-fetch"
import { cache } from "react"

import type { paths } from "./schema"

const baseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000"

const wake = cache(async (): Promise<void> => {
  await fetch(`${baseUrl}/api/health`, { cache: "no-store" }).catch(
    () => undefined
  )
})

export const serverApi = createClient<paths>({ baseUrl, cache: "no-store" })

serverApi.use({
  async onRequest() {
    await wake()
    return undefined
  },
})

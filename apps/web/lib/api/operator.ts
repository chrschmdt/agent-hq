import "server-only"

import createClient from "openapi-fetch"

import { isAdmin } from "@/auth"

import type { paths } from "./schema"

const baseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000"

export const operatorApi = createClient<paths>({ baseUrl, cache: "no-store" })

operatorApi.use({
  async onRequest({ request }) {
    if (!(await isAdmin())) {
      throw new Error("The operator's api is only for the signed-in admin.")
    }
    request.headers.set(
      "Authorization",
      `Bearer ${process.env.AHQ_OPERATOR_TOKEN ?? ""}`
    )
    return request
  },
})

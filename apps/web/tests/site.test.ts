import { afterEach, describe, expect, it, vi } from "vitest"

import robots from "@/app/robots"
import sitemap from "@/app/sitemap"
import { isAdminPage, siteUrl } from "@/lib/site"

describe("the control room's public address", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it("is AHQ_SITE_URL, else the production domain Vercel names", () => {
    vi.stubEnv("AHQ_SITE_URL", "")
    vi.stubEnv("VERCEL_PROJECT_PRODUCTION_URL", "ahq-abc.vercel.app")
    expect(siteUrl().origin).toBe("https://ahq-abc.vercel.app")
    vi.stubEnv("AHQ_SITE_URL", "https://agent-hq.example")
    expect(siteUrl().origin).toBe("https://agent-hq.example")
  })

  it("lets crawlers read the public pages of production only", () => {
    vi.stubEnv("AHQ_SITE_URL", "https://agent-hq.example")
    vi.stubEnv("VERCEL_ENV", "preview")
    expect(robots().rules).toEqual({ userAgent: "*", disallow: "/" })
    vi.stubEnv("VERCEL_ENV", "production")
    expect(robots()).toMatchObject({
      sitemap: "https://agent-hq.example/sitemap.xml",
      rules: { disallow: ["/admin/", "/auth/", "/api/", "/mcp/"] },
    })
    expect(sitemap().map((page) => page.url)).toContain(
      "https://agent-hq.example/agents/support"
    )
  })
})

describe("page analytics", () => {
  it("leave out the admin's pages and sign-in, and count the rest", () => {
    expect(isAdminPage("https://agent-hq.example/admin/data")).toBe(true)
    expect(isAdminPage("https://agent-hq.example/auth/signin")).toBe(true)
    expect(isAdminPage("https://agent-hq.example/overview")).toBe(false)
    expect(isAdminPage("https://agent-hq.example/administrators")).toBe(false)
  })
})

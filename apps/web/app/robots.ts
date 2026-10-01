import type { MetadataRoute } from "next"

import { isProduction, siteUrl } from "@/lib/site"

export default function robots(): MetadataRoute.Robots {
  if (!isProduction()) {
    return { rules: { userAgent: "*", disallow: "/" } }
  }
  const site = siteUrl()
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/admin/", "/auth/", "/api/", "/mcp/"],
    },
    sitemap: new URL("/sitemap.xml", site).toString(),
    host: site.origin,
  }
}

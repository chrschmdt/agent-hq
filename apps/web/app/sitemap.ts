import type { MetadataRoute } from "next"

import { PUBLIC_PAGES, siteUrl } from "@/lib/site"

export default function sitemap(): MetadataRoute.Sitemap {
  const site = siteUrl()
  return PUBLIC_PAGES.map((path) => ({
    url: new URL(path, site).toString(),
    changeFrequency: "weekly",
    priority: path === "/overview" ? 1 : 0.5,
  }))
}

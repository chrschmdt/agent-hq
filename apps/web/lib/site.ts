export function siteUrl(): URL {
  const configured = process.env.AHQ_SITE_URL
  if (configured) {
    return new URL(configured)
  }
  const production = process.env.VERCEL_PROJECT_PRODUCTION_URL
  return new URL(production ? `https://${production}` : "http://localhost:3000")
}

export function isProduction(): boolean {
  return process.env.VERCEL_ENV === "production"
}

export const PUBLIC_PAGES = [
  "/overview",
  "/work",
  "/agents",
  "/agents/dispatcher",
  "/agents/support",
  "/agents/ops",
  "/agents/insights",
  "/approvals",
  "/incidents",
  "/proposals",
  "/evals",
  "/quality",
]

const ADMIN_PATHS = ["/admin", "/auth"]

export function isAdminPage(url: string): boolean {
  const { pathname } = new URL(url, "http://localhost")
  return ADMIN_PATHS.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  )
}

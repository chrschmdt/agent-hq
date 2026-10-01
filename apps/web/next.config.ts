import type { NextConfig } from "next"

const apiOrigin = process.env.API_INTERNAL_URL ?? "http://localhost:8000"

const securityHeaders = [
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
]

const nextConfig: NextConfig = {
  devIndicators: { position: "bottom-right" },
  poweredByHeader: false,
  headers() {
    return [{ source: "/:path*", headers: securityHeaders }]
  },
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return []
    }
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/mcp/:path*", destination: `${apiOrigin}/mcp/:path*` },
    ]
  },
}

export default nextConfig
